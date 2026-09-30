"""Fotos de Obra - Maison Plage.

Organiza fotos da obra por pavimento, dia e servico.
Armazena em disco (FOTOS_DIR) e guarda metadados em SQLite.
"""
import hashlib
import hmac
import io
import os
import re
import secrets
import sqlite3
import time
import uuid
import zipfile
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

BASE = Path(__file__).parent
STORAGE = Path(os.environ.get("FOTOS_DIR", BASE / "storage"))
ORIGINAIS = STORAGE / "originais"
THUMBS = STORAGE / "thumbs"
DB_PATH = STORAGE / "fotos.db"
SECRET = os.environ.get("FOTOS_SECRET") or secrets.token_hex(32)
MAX_BYTES = 25 * 1024 * 1024
EXT_OK = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

for d in (ORIGINAIS, THUMBS):
    d.mkdir(parents=True, exist_ok=True)


def carregar_usuarios() -> dict[str, str]:
    """FOTOS_USERS='ana:senha1,joao:senha2'. Sem variavel: admin/admin (so para testes)."""
    raw = os.environ.get("FOTOS_USERS", "admin:admin")
    users = {}
    for par in raw.split(","):
        if ":" in par:
            nome, senha = par.split(":", 1)
            users[nome.strip()] = senha.strip()
    return users


USUARIOS = carregar_usuarios()


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


with db() as _c:
    _c.execute(
        """CREATE TABLE IF NOT EXISTS fotos(
        id TEXT PRIMARY KEY, arquivo TEXT, nome_original TEXT,
        pavimento TEXT, servico TEXT, dia TEXT, observacao TEXT,
        autor TEXT, criado_em REAL)"""
    )

app = FastAPI(title="Fotos de Obra")


# ---------- autenticacao (cookie assinado) ----------
def assinar(usuario: str) -> str:
    sig = hmac.new(SECRET.encode(), usuario.encode(), hashlib.sha256).hexdigest()
    return f"{usuario}|{sig}"


def usuario_atual(request: Request) -> str:
    cookie = request.cookies.get("sessao", "")
    usuario, _, sig = cookie.partition("|")
    esperado = assinar(usuario).partition("|")[2] if usuario else ""
    if not usuario or not hmac.compare_digest(sig, esperado) or usuario not in USUARIOS:
        raise HTTPException(401, "Nao autenticado")
    return usuario


@app.post("/api/login")
def login(usuario: str = Form(...), senha: str = Form(...)):
    if usuario not in USUARIOS or not hmac.compare_digest(USUARIOS[usuario], senha):
        raise HTTPException(401, "Usuario ou senha invalidos")
    resp = JSONResponse({"usuario": usuario})
    resp.set_cookie("sessao", assinar(usuario), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("sessao")
    return resp


@app.get("/api/me")
def me(usuario: str = Depends(usuario_atual)):
    return {"usuario": usuario}


# ---------- fotos ----------
def limpar(txt: str) -> str:
    return re.sub(r"\s+", " ", txt).strip()


def slug(txt: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", txt).strip("_") or "sem_nome"


def linha_para_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["url"] = f"/api/fotos/{d['id']}/arquivo"
    d["thumb"] = f"/api/fotos/{d['id']}/thumb"
    return d


@app.post("/api/fotos")
async def enviar(
    arquivos: list[UploadFile] = File(...),
    pavimento: str = Form(...),
    servico: str = Form(...),
    dia: str = Form(""),
    observacao: str = Form(""),
    usuario: str = Depends(usuario_atual),
):
    pavimento, servico = limpar(pavimento), limpar(servico)
    if not pavimento or not servico:
        raise HTTPException(400, "Pavimento e servico sao obrigatorios")
    dia = dia or date.today().isoformat()
    try:
        date.fromisoformat(dia)
    except ValueError:
        raise HTTPException(400, "Data invalida")

    pasta = ORIGINAIS / slug(pavimento) / dia / slug(servico)
    pasta.mkdir(parents=True, exist_ok=True)
    salvas = []
    for up in arquivos:
        ext = Path(up.filename or "").suffix.lower()
        if ext not in EXT_OK:
            raise HTTPException(400, f"Formato nao suportado: {up.filename}")
        conteudo = await up.read()
        if len(conteudo) > MAX_BYTES:
            raise HTTPException(413, f"Arquivo muito grande: {up.filename}")
        try:
            img = Image.open(io.BytesIO(conteudo))
            img = ImageOps.exif_transpose(img).convert("RGB")
        except Exception:
            raise HTTPException(400, f"Imagem invalida: {up.filename}")
        fid = uuid.uuid4().hex
        destino = pasta / f"{fid}.jpg"
        img.save(destino, "JPEG", quality=90)
        img.thumbnail((400, 400))
        img.save(THUMBS / f"{fid}.jpg", "JPEG", quality=75)
        with db() as c:
            c.execute(
                "INSERT INTO fotos VALUES(?,?,?,?,?,?,?,?,?)",
                (fid, str(destino.relative_to(ORIGINAIS)), up.filename, pavimento,
                 servico, dia, observacao, usuario, time.time()),
            )
        salvas.append(fid)
    return {"enviadas": len(salvas), "ids": salvas}


def filtrar(pavimento: str, servico: str, dia: str, de: str, ate: str):
    sql, args = "SELECT * FROM fotos WHERE 1=1", []
    for campo, valor in (("pavimento", pavimento), ("servico", servico), ("dia", dia)):
        if valor:
            sql += f" AND {campo}=?"
            args.append(valor)
    if de:
        sql += " AND dia>=?"
        args.append(de)
    if ate:
        sql += " AND dia<=?"
        args.append(ate)
    return sql + " ORDER BY dia DESC, criado_em DESC", args


@app.get("/api/fotos")
def listar(pavimento: str = "", servico: str = "", dia: str = "", de: str = "", ate: str = "",
           _: str = Depends(usuario_atual)):
    sql, args = filtrar(pavimento, servico, dia, de, ate)
    with db() as c:
        return [linha_para_dict(r) for r in c.execute(sql, args)]


@app.get("/api/opcoes")
def opcoes(_: str = Depends(usuario_atual)):
    with db() as c:
        pav = [r[0] for r in c.execute("SELECT DISTINCT pavimento FROM fotos ORDER BY 1")]
        srv = [r[0] for r in c.execute("SELECT DISTINCT servico FROM fotos ORDER BY 1")]
    return {"pavimentos": pav, "servicos": srv}


def _foto(fid: str) -> sqlite3.Row:
    with db() as c:
        r = c.execute("SELECT * FROM fotos WHERE id=?", (fid,)).fetchone()
    if not r:
        raise HTTPException(404, "Foto nao encontrada")
    return r


@app.get("/api/fotos/{fid}/arquivo")
def arquivo(fid: str, download: bool = False, _: str = Depends(usuario_atual)):
    r = _foto(fid)
    nome = f"{slug(r['pavimento'])}_{r['dia']}_{slug(r['servico'])}_{fid[:6]}.jpg"
    return FileResponse(ORIGINAIS / r["arquivo"], media_type="image/jpeg",
                        filename=nome if download else None,
                        content_disposition_type="attachment" if download else "inline")


@app.get("/api/fotos/{fid}/thumb")
def thumb(fid: str, _: str = Depends(usuario_atual)):
    _foto(fid)
    return FileResponse(THUMBS / f"{fid}.jpg", media_type="image/jpeg")


@app.delete("/api/fotos/{fid}")
def apagar(fid: str, usuario: str = Depends(usuario_atual)):
    r = _foto(fid)
    (ORIGINAIS / r["arquivo"]).unlink(missing_ok=True)
    (THUMBS / f"{fid}.jpg").unlink(missing_ok=True)
    with db() as c:
        c.execute("DELETE FROM fotos WHERE id=?", (fid,))
    return {"ok": True}


@app.get("/api/zip")
def baixar_zip(pavimento: str = "", servico: str = "", dia: str = "", de: str = "", ate: str = "",
               _: str = Depends(usuario_atual)):
    """ZIP com a estrutura Pavimento/Dia/Servico para guardar no desktop."""
    sql, args = filtrar(pavimento, servico, dia, de, ate)
    with db() as c:
        linhas = c.execute(sql, args).fetchall()
    if not linhas:
        raise HTTPException(404, "Nenhuma foto para os filtros")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for r in linhas:
            z.write(ORIGINAIS / r["arquivo"],
                    f"{slug(r['pavimento'])}/{r['dia']}/{slug(r['servico'])}/{r['id'][:8]}.jpg")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="fotos_obra.zip"'})


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
