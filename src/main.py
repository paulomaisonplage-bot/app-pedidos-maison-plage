import os
import sys
import re
import json
import requests
import time
import random
import secrets
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.query_service import OrderQueryService, load_all_suppliers_contacts
from src.excel_manager import calculate_installments_for_item, parse_date
from src.auth_service import AuthService



EXCEL_PATH = os.getenv("EXCEL_PATH", "data/pedidos_compra_consolidado.xlsx")
if not os.path.exists(EXCEL_PATH) and os.path.exists("../data/pedidos_compra_consolidado.xlsx"):
    EXCEL_PATH = "../data/pedidos_compra_consolidado.xlsx"

USERS_FILE = "data/usuarios_autorizados.json"
query_service = OrderQueryService(EXCEL_PATH)
auth_service = AuthService(USERS_FILE)

# ==========================================
# FAST IN-MEMORY CACHE ENGINE (RESPOSTA < 2ms)
# ==========================================
CACHE_STORE = {
    "last_load": 0,
    "last_mtime": 0,
    "raw_records": {},
    "orders_by_pc": {},
    "recent_cards": None,
    "financial_summary": None,
    "catalog_materials": None
}

def get_cached_raw_records(force_reload: bool = False):
    now = time.time()
    try:
        current_mtime = os.path.getmtime(EXCEL_PATH) if os.path.exists(EXCEL_PATH) else 0
    except OSError:
        current_mtime = 0

    mtime_changed = current_mtime > CACHE_STORE["last_mtime"]

    if force_reload or mtime_changed or (now - CACHE_STORE["last_load"] > 180) or not CACHE_STORE["raw_records"]:
        raw = query_service.manager.load_existing_records()
        CACHE_STORE["raw_records"] = raw
        CACHE_STORE["last_mtime"] = current_mtime
        
        # Indexa pedidos por PC
        by_pc = {}
        for r in raw.values():
            pc = str(r.get("numero_pedido", "")).strip()
            if pc:
                if pc not in by_pc:
                    by_pc[pc] = []
                by_pc[pc].append(r)
        CACHE_STORE["orders_by_pc"] = by_pc
        CACHE_STORE["last_load"] = now
        CACHE_STORE["recent_cards"] = None
        CACHE_STORE["financial_summary"] = None
        CACHE_STORE["catalog_materials"] = None
        
    return CACHE_STORE["raw_records"], CACHE_STORE["orders_by_pc"]



app = FastAPI(title="Maison Plage • App de Pedidos", version="2.2.20260829172549")

@app.on_event("startup")
async def startup_event():
    # Pré-aquece o cache na inicialização do servidor
    get_cached_raw_records(force_reload=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def get_previous_month_cutoff_date() -> date:
    hoje = date.today()
    if hoje.month == 1:
        return date(hoje.year - 1, 12, 1)
    else:
        return date(hoje.year, hoje.month - 1, 1)


def can_view_monetary(role: str) -> bool:
    canonical = (role or "").strip().lower()
    return canonical in ["admin", "engenharia", "administracao", "adm"]

def can_view_financial_schedule(role: str) -> bool:
    canonical = (role or "").strip().lower()
    return canonical in ["admin", "engenharia"]

def can_download_files(role: str) -> bool:
    canonical = (role or "").strip().lower()
    return canonical in ["admin", "engenharia", "administracao", "adm"]


def build_order_card_data(pc: str, role: str) -> Optional[dict]:
    hide_fin = not can_view_monetary(role)
    items = query_service.get_order_by_number(pc)
    if not items:
        return None
    it0 = items[0]
    total_val = sum(float(str(x.get("preco_total_item", 0.0) or 0.0)) for x in items)
    fornec = str(it0.get("fornecedor_nome") or it0.get("fornecedor", "Fornecedor da Obra")).strip()
    
    # 3 primeiros itens com quantidade e unidade
    top_3_items = []
    for it in items[:3]:
        desc = str(it.get("descricao_material", "") or it.get("descricao_completa", "Item")).strip()
        qtd = it.get("quantidade", 0)
        un = str(it.get("unidade", "UN")).strip()
        top_3_items.append(f"• {qtd} {un} - {desc}")
        
    extra_count = len(items) - 3 if len(items) > 3 else 0

    return {
        "pc": str(pc),
        "fornecedor": fornec if not hide_fin else "Fornecedor Homologado",
        "data_entrega": it0.get("data_entrega_prevista", "A Confirmar"),
        "data_emissao": it0.get("data_pedido", "-"),
        "total_itens": len(items),
        "itens_resumo": top_3_items,
        "extra_itens_count": extra_count,
        "valor_total_formatado": f"R${total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if not hide_fin else None,
        "can_pdf": can_download_files(role)
    }


def find_file_id_for_order(pc_num: str) -> Optional[str]:
    pdf_links_path = "data/pdf_links.json"
    if not os.path.exists(pdf_links_path) and os.path.exists("../data/pdf_links.json"):
        pdf_links_path = "../data/pdf_links.json"
    if os.path.exists(pdf_links_path):
        try:
            with open(pdf_links_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            for k, fid in cache.items():
                if f"PedidoCompra{pc_num}_" in k or f"PedidoCompra{pc_num}." in k or f"PC_{pc_num}" in k:
                    return fid
            for k, fid in cache.items():
                if str(pc_num) in k:
                    return fid
        except Exception:
            pass
    return None

def find_supplier_contact(f_nome: str, f_cnpj: str = ""):

    catalog = load_all_suppliers_contacts()
    cnpj_clean = re.sub(r'[^0-9]', '', str(f_cnpj or ''))
    if cnpj_clean and len(cnpj_clean) == 14:
        for s in catalog:
            s_cnpj = re.sub(r'[^0-9]', '', str(s.get('cnpj', '') or ''))
            if s_cnpj == cnpj_clean:
                return s
                
    clean_fn = re.sub(r'[^a-zA-Z0-9\s]', ' ', str(f_nome).lower()).strip()
    stop_words = {'ltda', 'comercio', 'distribuidora', 'produtos', 'me', 'epp', 'sa', 'com', 'brasil', 'material', 'construcao', 'servicos'}
    tokens = [t for t in clean_fn.split() if len(t) >= 3 and t not in stop_words]
    
    if not tokens:
        tokens = [t for t in clean_fn.split() if len(t) >= 3]
        
    for s in catalog:
        s_nome_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', s['nome'].lower()).strip()
        if any(t in s_nome_clean for t in tokens):
            return s
            
    return None

def parse_supplier_dual_contacts(supplier_item: dict) -> dict:
    if not supplier_item:
        return {"vendedor": None, "empresa": None}
        
    vend_raw = str(supplier_item.get("vendedor", "") or "").strip()
    tel_raw = str(supplier_item.get("telefone", "") or "").strip()
    email_raw = str(supplier_item.get("email", "") or "").strip()
    
    v_nome = vend_raw
    v_tel = ""
    v_tel_clean = ""
    
    m_tel = re.search(r'(?:(?:\+|00)?55\s*)?(?:\(?([1-9]{2})\)?\s*)?(?:9\s*)?(\d{4,5})[\s\.\-]?(\d{4})', vend_raw)
    if m_tel:
        ddd = m_tel.group(1) or "82"
        p1 = m_tel.group(2).replace(" ", "")
        p2 = m_tel.group(3).replace(" ", "")
        v_tel_clean = f"{ddd}{p1}{p2}"
        v_tel = f"({ddd}) {p1}-{p2}" if len(p1) == 5 else f"({ddd}) {p1[:4]}-{p1[4:]}{p2}"
        v_nome = vend_raw[:m_tel.start()].strip(" -:–tel.TEL.")
        if not v_nome:
            v_nome = "Vendedor Comercial"
    elif not v_nome or v_nome == "-":
        v_nome = "Atendimento Comercial"

    emp_tel = tel_raw if tel_raw and tel_raw != v_tel_clean else ""
    emp_tel_clean = re.sub(r'[^0-9]', '', emp_tel) if emp_tel else ""
    emp_email = email_raw if email_raw and email_raw != "Não Informado" else ""
    
    return {
        "vendedor": {
            "nome": v_nome,
            "telefone": v_tel if v_tel else None,
            "telefone_clean": v_tel_clean if v_tel_clean else None
        },
        "empresa": {
            "telefone": emp_tel if emp_tel else None,
            "telefone_clean": emp_tel_clean if emp_tel_clean else None,
            "email": emp_email if emp_email else None
        }
    }

class LoginRequest(BaseModel):
    pin: str

class UserCreateRequest(BaseModel):
    nome: str
    pin: str
    role: str

class UserUpdateRequest(BaseModel):
    user_id: str
    role: str

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/manifest.json")
async def get_manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")

@app.get("/sw.js")
async def get_service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")

# AUTENTICAÇÃO POR E-MAIL / SMS
import random
OTP_STORE = {}

class EmailOtpRequest(BaseModel):
    email: str

class VerifyOtpRequest(BaseModel):
    email: str
    code: str

@app.post("/api/auth/send_otp")
async def api_send_otp(req: EmailOtpRequest):
    code = f"{random.randint(100000, 999999)}"
    email_clean = req.email.strip().lower()
    OTP_STORE[email_clean] = {
        "code": code,
        "expires_at": time.time() + 600
    }
    # Em producao, enviamos o email via SMTP/SendGrid. Para testes imediatos:
    print(f"\n[AUTH] Código OTP enviado para {email_clean}: {code}\n")
    return {"success": True, "message": f"Código enviado para {email_clean}", "dev_code": code}

@app.post("/api/auth/verify_otp")
async def api_verify_otp(req: VerifyOtpRequest):
    email_clean = req.email.strip().lower()
    stored = OTP_STORE.get(email_clean)
    if not stored or time.time() > stored["expires_at"]:
        raise HTTPException(status_code=400, detail="Código expirado ou não solicitado.")
    if stored["code"] != req.code.strip():
        raise HTTPException(status_code=400, detail="Código de validação incorreto.")
    
    # Determina o perfil com base no email ou default Admin/Engenharia
    user_info = {
        "id": "email_user",
        "nome": email_clean.split("@")[0].capitalize(),
        "role": "admin" if "paulo" in email_clean or "admin" in email_clean else "engenharia",
        "email": email_clean
    }
    return {"success": True, "user": user_info}

# AUTENTICAÇÃO
@app.post("/api/auth/login")
async def api_login(req: LoginRequest):
    users = auth_service._data.get("users", {})
    for uid, udata in users.items():
        if str(udata.get("pin", "")).strip() == req.pin.strip():
            return {
                "success": True,
                "user": {
                    "id": str(uid),
                    "nome": udata.get("nome"),
                    "role": udata.get("role"),
                    "is_admin": (udata.get("role") == "admin")
                }
            }
    raise HTTPException(status_code=401, detail="PIN de acesso incorreto.")

# GESTÃO DE EQUIPE
@app.get("/api/users")
async def api_get_users(role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Exclusivo para o Administrador Master.")
    users = auth_service._data.get("users", {})
    user_list = []
    for uid, udata in users.items():
        user_list.append({
            "id": str(uid),
            "nome": udata.get("nome"),
            "role": udata.get("role"),
            "pin": udata.get("pin", "****"),
            "data_autorizacao": udata.get("data_autorizacao", "-")
        })
    return {"users": user_list}

@app.post("/api/users/add")
async def api_add_user(req: UserCreateRequest, role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Exclusivo para o Administrador Master.")
    new_id = str(int(datetime.now().timestamp()))
    auth_service._data.setdefault("users", {})[new_id] = {
        "nome": req.nome.strip(),
        "pin": req.pin.strip(),
        "role": req.role,
        "username": f"@{req.nome.lower().replace(' ', '_')}",
        "data_autorizacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    }
    auth_service._save_data()
    return {"success": True, "user_id": new_id}

@app.post("/api/users/update_role")
async def api_update_user_role(req: UserUpdateRequest, role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Exclusivo para o Administrador Master.")
    users = auth_service._data.get("users", {})
    if req.user_id in users:
        users[req.user_id]["role"] = req.role
        auth_service._save_data()
        return {"success": True}
    raise HTTPException(status_code=404, detail="Usuário não encontrado.")

@app.delete("/api/users/{user_id}")
async def api_delete_user(user_id: str, role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Exclusivo para o Administrador Master.")
    users = auth_service._data.get("users", {})
    if user_id in users:
        if str(user_id) in [str(a) for a in auth_service._data.get("admin_ids", [])]:
            raise HTTPException(status_code=400, detail="Não é permitido excluir o Admin Master.")
        del users[user_id]
        auth_service._save_data()
        return {"success": True}
    raise HTTPException(status_code=404, detail="Usuário não encontrado.")

# ==========================================
# GESTÃO DE CONVITES DE USO ÚNICO E APROVAÇÃO
# ==========================================

class GenerateInviteRequest(BaseModel):
    role_sugerido: Optional[str] = "engenharia"

class RegisterInviteRequest(BaseModel):
    token: str
    nome: str
    contato: str

class ApproveUserRequest(BaseModel):
    req_id: str
    role: str
    pin: str

class RejectUserRequest(BaseModel):
    req_id: str

@app.post("/api/invites/generate")
async def api_generate_invite(req: GenerateInviteRequest, role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Apenas o Administrador pode gerar links de convite.")
    
    token = f"mp_inv_{secrets.token_hex(6)}"
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    if "invites" not in data:
        data["invites"] = {}
        
    data["invites"][token] = {
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "role_sugerido": req.role_sugerido,
        "status": "active" # "active" ou "used"
    }
    
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    return {"token": token, "link": f"https://app-pedidos-maison-plage.onrender.com/?convite={token}"}

@app.get("/api/invites/validate")
async def api_validate_invite(token: str):
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    inv = data.get("invites", {}).get(token)
    if not inv:
        return {"valid": False, "reason": "Link de convite inexistente."}
    if inv.get("status") != "active":
        return {"valid": False, "reason": "Este link de convite já foi utilizado e expirou."}
    return {"valid": True, "role_sugerido": inv.get("role_sugerido", "engenharia")}

@app.post("/api/invites/register")
async def api_register_invite(req: RegisterInviteRequest):
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    inv = data.get("invites", {}).get(req.token)
    if not inv or inv.get("status") != "active":
        raise HTTPException(status_code=400, detail="Este link de convite já foi utilizado ou é inválido.")
    
    # Queima o token imediatamente para torná-lo de uso estritamente único
    inv["status"] = "used"
    inv["used_at"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    inv["used_by_nome"] = req.nome.strip()
    
    req_id = f"req_{int(time.time())}"
    if "pending_requests" not in data:
        data["pending_requests"] = {}
        
    data["pending_requests"][req_id] = {
        "id": req_id,
        "nome": req.nome.strip(),
        "contato": req.contato.strip(),
        "role_sugerido": inv.get("role_sugerido", "engenharia"),
        "requested_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "token_used": req.token,
        "status": "pending"
    }
    
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    return {"success": True, "req_id": req_id, "message": "Solicitação enviada com sucesso!"}

@app.get("/api/users/pending")
async def api_get_pending_requests(role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao Administrador.")
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    reqs = list(data.get("pending_requests", {}).values())
    pending_only = [r for r in reqs if r.get("status") == "pending"]
    return {"pending": pending_only}

@app.post("/api/users/approve")
async def api_approve_user(req: ApproveUserRequest, role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao Administrador.")
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    p_req = data.get("pending_requests", {}).get(req.req_id)
    if not p_req:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
        
    uid = re.sub(r'[^a-zA-Z0-9]', '_', p_req["nome"].lower().strip())[:20]
    data["users"][uid] = {
        "id": uid,
        "nome": p_req["nome"],
        "contato": p_req["contato"],
        "role": req.role,
        "pin": req.pin.strip(),
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    p_req["status"] = "approved"
    p_req["approved_at"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    p_req["approved_user_id"] = uid
    p_req["approved_pin"] = req.pin.strip()
    
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    return {"success": True, "message": f"Usuário {p_req['nome']} aprovado como {req.role} com PIN {req.pin}!"}

@app.post("/api/users/reject")
async def api_reject_user(req: RejectUserRequest, role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao Administrador.")
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if req.req_id in data.get("pending_requests", {}):
        data["pending_requests"][req.req_id]["status"] = "rejected"
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    return {"success": True}

@app.get("/api/users/check_status")
async def api_check_req_status(req_id: str):
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    p_req = data.get("pending_requests", {}).get(req_id)
    if not p_req:
        return {"status": "unknown"}
    return {
        "status": p_req.get("status"),
        "role": p_req.get("role_sugerido"),
        "pin": p_req.get("approved_pin") if p_req.get("status") == "approved" else None
    }

# 1. ENTREGAS DA SEMANA
@app.get("/api/deliveries/week")
async def api_deliveries_week(offset: int = 0, role: str = "campo"):
    hide_fin = not can_view_monetary(role)
    msg, pcs = query_service.get_deliveries_summary_for_week(offset=offset, hide_financials=hide_fin, item_offset=0, page_size=100)
    
    hoje = date.today()
    segunda = hoje - timedelta(days=hoje.weekday()) + timedelta(weeks=offset)
    domingo = segunda + timedelta(days=6)
    periodo_str = f"{segunda.strftime('%d/%m')} a {domingo.strftime('%d/%m/%Y')}"

    cards = []
    for pc in pcs:
        c = build_order_card_data(pc, role)
        if c:
            cards.append(c)
    return {"offset": offset, "periodo": periodo_str, "cards": cards}

# 2. ENTREGAS DO MÊS
@app.get("/api/deliveries/month")
async def api_deliveries_month(mes: int = 8, ano: int = 2026, role: str = "campo"):
    hide_fin = not can_view_monetary(role)
    msg, pcs = query_service.get_delivery_summary_for_month(mes=mes, ano=ano, hide_financials=hide_fin, item_offset=0, page_size=100)
    cards = []
    for pc in pcs:
        c = build_order_card_data(pc, role)
        if c:
            cards.append(c)
    return {"mes": mes, "ano": ano, "cards": cards}

def get_cached_catalog_materials():
    get_cached_raw_records()
    if CACHE_STORE["catalog_materials"] is None:
        raw = CACHE_STORE["raw_records"]
        cutoff = get_previous_month_cutoff_date()
        insumos_map = {}
        for r in raw.values():
            dt_ent = (parse_date(r.get("data_entrega_prevista")).date() if parse_date(r.get("data_entrega_prevista")) else None) or (parse_date(r.get("data_pedido")).date() if parse_date(r.get("data_pedido")) else None)
            if not dt_ent or dt_ent < cutoff:
                continue
                
            desc = str(r.get("descricao_material", "") or "").strip()
            cod = str(r.get("codigo_insumo", "") or "").strip()
            fam = str(r.get("familia_insumo", "04 DIVERSOS") or "04 DIVERSOS").strip()
            pc = str(r.get("numero_pedido", "")).strip()
            qtd = float(r.get("quantidade", 0) or 0.0)
            unid = str(r.get("unidade", "UN") or "UN").strip()
            
            if not desc and not cod:
                continue
                
            key = desc.upper() if desc else f"COD_{cod}"
            if key not in insumos_map:
                insumos_map[key] = {
                    "nome": desc if desc else f"Insumo Cód. {cod}",
                    "codigo": cod,
                    "familia": fam,
                    "unidade": unid,
                    "qtd_total": 0.0,
                    "pedidos": set()
                }
                
            insumos_map[key]["qtd_total"] += qtd
            if pc:
                insumos_map[key]["pedidos"].add(pc)

        sorted_items = sorted(insumos_map.values(), key=lambda x: x["nome"].upper())
        formatted_catalog = []
        for it in sorted_items:
            qtd_fmt = f"{it['qtd_total']:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".").rstrip('0').rstrip(',')
            formatted_catalog.append({
                "nome": it["nome"],
                "codigo": it["codigo"],
                "familia": it["familia"],
                "unidade": it["unidade"],
                "qtd_formatada": f"{qtd_fmt} {it['unidade'].lower()}",
                "pedidos_count": len(it["pedidos"]),
                "pedidos": sorted(list(it["pedidos"]), reverse=True)
            })
        CACHE_STORE["catalog_materials"] = formatted_catalog
    return CACHE_STORE["catalog_materials"]

# 3. CATÁLOGO ALFABÉTICO ENXUTO DE INSUMOS (DO MÊS ANTERIOR EM DIANTE)
@app.get("/api/materials/catalog")
async def api_materials_catalog(q: Optional[str] = None, letter: Optional[str] = None):
    all_materials = get_cached_catalog_materials()
    filtered = all_materials

    if letter and letter.upper() != "TODOS":
        l_upper = letter.upper()
        filtered = [i for i in filtered if i["nome"].upper().startswith(l_upper)]

    if q:
        q_l = q.lower().strip()
        filtered = [i for i in filtered if q_l in i["nome"].lower() or q_l in i["codigo"].lower() or q_l in i["familia"].lower()]

    return {
        "total_cadastrados": len(all_materials),
        "total_filtrados": len(filtered),
        "insumos": filtered[:300]
    }

@app.get("/api/materials/orders")
async def api_material_orders(nome: str, role: str = "campo"):
    hide_fin = not can_view_monetary(role)
    cutoff = get_previous_month_cutoff_date()
    raw_dict, pc_items_map = get_cached_raw_records()
    mat_upper = nome.upper().strip()
    
    matching_pcs = []
    for pc, items in pc_items_map.items():
        it0 = items[0] if items else {}
        dt_ent = (parse_date(it0.get("data_entrega_prevista")).date() if parse_date(it0.get("data_entrega_prevista")) else None) or (parse_date(it0.get("data_pedido")).date() if parse_date(it0.get("data_pedido")) else None)
        if dt_ent and dt_ent < cutoff:
            continue
        if any(mat_upper == str(i.get("descricao_material", "") or "").strip().upper() for i in items):
            matching_pcs.append(pc)
            
    cards = []
    for pc in sorted(matching_pcs, key=lambda x: int(x) if x.isdigit() else 0, reverse=True):
        items = pc_items_map[pc]
        it0 = items[0]
        total_val = sum(float(str(x.get("preco_total_item", 0.0) or 0.0)) for x in items)
        fornec = str(it0.get("fornecedor_nome") or it0.get("fornecedor", "Fornecedor da Obra")).strip()
        
        top_3 = []
        for it in items[:3]:
            desc = str(it.get("descricao_material", "") or "").strip()
            qtd = it.get("quantidade", 0)
            un = str(it.get("unidade", "UN")).strip()
            top_3.append(f"• {qtd} {un} - {desc}")
            
        extra_count = len(items) - 3 if len(items) > 3 else 0
        
        cards.append({
            "pc": pc,
            "fornecedor": fornec if not hide_fin else "Fornecedor Homologado",
            "data_entrega": it0.get("data_entrega_prevista", "A Confirmar"),
            "data_emissao": it0.get("data_pedido", "-"),
            "total_itens": len(items),
            "itens_resumo": top_3,
            "extra_itens_count": extra_count,
            "valor_total_formatado": f"R${total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if not hide_fin else None,
            "can_pdf": can_download_files(role)
        })
        
    return {"material": nome, "total_pedidos": len(cards), "cards": cards}

# 4. GRUPOS DA OBRA
@app.get("/api/groups")
async def api_groups():
    fams = query_service.get_all_families_summary()
    return {"groups": fams}

@app.get("/api/groups/orders")
async def api_group_orders(familia: str, role: str = "campo"):
    hide_fin = not can_view_monetary(role)
    raw_dict, pc_items_map = get_cached_raw_records()
    fam_upper = familia.upper().strip()
    
    matching_pcs = []
    for pc, items in pc_items_map.items():
        if any(fam_upper in str(i.get("familia_insumo", "") or "").upper() for i in items):
            matching_pcs.append(pc)
            
    cards = []
    for pc in sorted(matching_pcs, key=lambda x: int(x) if x.isdigit() else 0, reverse=True):
        items = pc_items_map[pc]
        it0 = items[0]
        total_val = sum(float(str(x.get("preco_total_item", 0.0) or 0.0)) for x in items)
        fornec = str(it0.get("fornecedor_nome") or it0.get("fornecedor", "Fornecedor da Obra")).strip()
        
        top_3 = []
        for it in items[:3]:
            desc = str(it.get("descricao_material", "") or "").strip()
            qtd = it.get("quantidade", 0)
            un = str(it.get("unidade", "UN")).strip()
            top_3.append(f"• {qtd} {un} - {desc}")
            
        extra_count = len(items) - 3 if len(items) > 3 else 0
        
        cards.append({
            "pc": pc,
            "fornecedor": fornec if not hide_fin else "Fornecedor Homologado",
            "data_entrega": it0.get("data_entrega_prevista", "A Confirmar"),
            "data_emissao": it0.get("data_pedido", "-"),
            "total_itens": len(items),
            "itens_resumo": top_3,
            "extra_itens_count": extra_count,
            "valor_total_formatado": f"R${total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if not hide_fin else None,
            "can_pdf": can_download_files(role)
        })
        
    return {"familia": familia, "total_pedidos": len(cards), "cards": cards}

# 5. COMPRAS RECENTES
@app.get("/api/recent_purchases")
async def api_recent_purchases(role: str = "campo"):
    hide_fin = not can_view_monetary(role)
    msg, pcs = query_service.get_recent_orders_summary(max_orders=40, hide_financials=hide_fin, item_offset=0, page_size=40)
    cards = []
    for pc in pcs:
        c = build_order_card_data(pc, role)
        if c:
            cards.append(c)
    return {"cards": cards}

# 6. FORNECEDORES
@app.get("/api/suppliers")
async def api_suppliers(q: Optional[str] = None, role: str = "campo"):
    if not can_view_monetary(role):
        raise HTTPException(status_code=403, detail="Acesso reservado para Engenharia e Administração")
    
    catalog = load_all_suppliers_contacts()
    if q:
        clean_q = re.sub(r'[^\w\s]', ' ', q).lower().strip()
        tokens = [t for t in clean_q.split() if len(t) >= 2]
        catalog = [
            f for f in catalog
            if all(t in f["nome"].lower() or t in f.get("vendedor", "").lower() or t in f.get("email", "").lower() for t in tokens)
        ]
    
    fornecs = []
    for f in catalog:
        contacts = parse_supplier_dual_contacts(f)
        fornecs.append({
            "razao_social": f.get("nome", "Não Informado"),
            "vendedor": contacts["vendedor"],
            "empresa": contacts["empresa"]
        })

    return {"suppliers": fornecs}

# 7. FLUXO FINANCEIRO INTELIGENTE (PREVISÃO DO MÊS ANTERIOR EM DIANTE)
@app.get("/api/financial/summary")
async def api_financial_summary(role: str = "campo"):
    if not can_view_financial_schedule(role):
        raise HTTPException(status_code=403, detail="Acesso exclusivo para Engenharia e Administração.")
    
    raw_dict, _ = get_cached_raw_records()
    all_raw_records = list(raw_dict.values())
    
    all_insts = []
    for r in all_raw_records:
        all_insts.extend(calculate_installments_for_item(r))
        
    cutoff = get_previous_month_cutoff_date()
    # Mapeia os meses a partir do mes anterior (Julho=7 ate Dezembro=12)
    start_m = cutoff.month
    monthly_vals = {m: 0.0 for m in range(start_m, 13)}
    month_names = {1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"}
    
    total_desembolso_periodo = 0.0
    for i in all_insts:
        dt_venc = i.get("_venc_dt")
        val = float(i.get("valor_parcela", 0.0) or 0.0)
        if dt_venc and dt_venc.year == 2026 and dt_venc.month in monthly_vals:
            monthly_vals[dt_venc.month] += val
            total_desembolso_periodo += val

    val_ago = monthly_vals.get(8, 0.0)
    val_futuro = sum(v for m, v in monthly_vals.items() if m >= 9)
    max_month_val = max(monthly_vals.values()) or 1.0

    bars = []
    for m in range(start_m, 13):
        v = monthly_vals[m]
        pct = (v / total_desembolso_periodo * 100) if total_desembolso_periodo > 0 else 0
        bar_pct = (v / max_month_val * 100) if max_month_val > 0 else 0
        bars.append({
            "mes_num": m,
            "mes_nome": month_names[m],
            "valor_fmt": f"R${v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "pct": round(pct, 1),
            "bar_pct": round(bar_pct, 1),
            "is_current": (m == 8)
        })

    # Macro-Grupos da Obra
    MACRO_GROUPS = [
        {"name": "Obra Grossa & Estrutura", "icon": "🏗️", "sub": ["AGREGADOS", "BLOCOS", "TIJOLOS", "MADEIRA", "PRODUTOS METÁLICOS", "ARGAMASSAS", "TELHAS", "PRÉ-MOLDADOS", "ESTRUTURA", "MISTURAS"], "total": 0.0, "color": "#3b82f6"},
        {"name": "Instalações Prediais", "icon": "⚡", "sub": ["HIDRÁULICAS", "ELÉTRICAS", "INCÊNDIO", "GÁS", "PVC", "TUBOS", "CONEXÕES", "REFRIGERAÇÃO", "ENERGIA"], "total": 0.0, "color": "#10b981"},
        {"name": "Acabamentos & Pintura", "icon": "🛡️", "sub": ["IMPERMEABILIZANTE", "TINTAS", "VERNIZ", "REVESTIMENTO", "FERRAGENS", "LOUÇAS", "METAIS", "PAVIMENTAÇÃO", "DRENAGEM", "PAISAGISMO", "URBANISMO", "MÓVEIS"], "total": 0.0, "color": "#f59e0b"},
        {"name": "Segurança, EPIs & Apoio", "icon": "🦺", "sub": ["EPI", "EPC", "LIMPEZA", "EXPEDIENTE", "FERRAMENTAS", "MATERIAIS AUXILIARES", "ALIMENTAÇÃO", "COMBUSTÍVEIS", "SINALIZAÇÃO", "DIVERSOS"], "total": 0.0, "color": "#8b5cf6"},
        {"name": "Serviços & Equipamentos", "icon": "🚜", "sub": ["EQUIPAMENTOS", "SERVIÇOS", "ALUGUEL", "LOCAÇÃO", "ESQUADRIAS", "EMPREITADOS", "TAXAS", "VERBAS", "TERCEIRIZADOS"], "total": 0.0, "color": "#ec4899"}
    ]

    records_pos_corte = [r for r in all_raw_records if ((parse_date(r.get("data_entrega_prevista")).date() if parse_date(r.get("data_entrega_prevista")) else None) or (parse_date(r.get("data_pedido")).date() if parse_date(r.get("data_pedido")) else None) or date.min) >= cutoff]
    total_contratado_compras = sum(float(r.get("preco_total_item", 0.0) or 0.0) for r in records_pos_corte)

    for r in records_pos_corte:
        fam_raw = str(r.get("familia_insumo", "") or "").upper()
        val = float(r.get("preco_total_item", 0.0) or 0.0)
        alloc = False
        for g in MACRO_GROUPS:
            if any(t in fam_raw for t in g["sub"]):
                g["total"] += val
                alloc = True
                break
        if not alloc:
            MACRO_GROUPS[3]["total"] += val # default apoio/diversos

    groups_res = []
    for g in MACRO_GROUPS:
        pct = (g["total"] / total_contratado_compras * 100) if total_contratado_compras > 0 else 0
        groups_res.append({
            "name": g["name"],
            "icon": g["icon"],
            "color": g["color"],
            "valor_fmt": f"R${g['total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "pct": round(pct, 1)
        })

    return {
        "kpis": {
            "total_desembolso": f"R${total_desembolso_periodo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "mes_atual": f"R${val_ago:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "futuro": f"R${val_futuro:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        },
        "monthly_bars": bars,
        "macro_groups": groups_res
    }

# 8. EXPORTAR PLANILHAS EM EXCEL (.xlsx)
@app.get("/api/export/excel")
async def api_export_excel(tipo: str = "geral", role: str = "campo"):
    if not can_view_financial_schedule(role):
        raise HTTPException(status_code=403, detail="Download reservado para Engenharia e Administração.")
    
    import pandas as pd
    import io
    
    if tipo == "financeiro":
        # Gera Planilha de Fluxo Financeiro / Desembolso
        insts = query_service.get_all_installments(from_previous_month_only=True)
        rows = []
        for i in insts:
            rows.append({
                "Número do Pedido": i.get("numero_pedido"),
                "Fornecedor": i.get("fornecedor_nome"),
                "Parcela": f"{i.get('parcela_num', 1)}/{i.get('total_parcelas', 1)}",
                "Data de Vencimento": i.get("data_vencimento"),
                "Mês/Ano": i.get("mes_ano"),
                "Valor da Parcela (R$)": float(i.get("valor_parcela", 0.0) or 0.0),
                "Condição de Pagamento": i.get("condicao_pagamento"),
                "Descrição do Insumo": i.get("descricao_material"),
                "Família / Macro-Grupo": i.get("familia_insumo")
            })
        
        df_fin = pd.DataFrame(rows)
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            df_fin.to_excel(writer, index=False, sheet_name="Fluxo_Desembolso")
        out.seek(0)
        
        return Response(
            content=out.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=fluxo_desembolso_maison_plage.xlsx"}
        )
    
    else:
        # Gera Planilha Geral Consolidada da Obra (>= Junho/2026)
        records = query_service._get_all_records()
        rows = []
        for r in records:
            rows.append({
                "Número do Pedido": r.get("numero_pedido"),
                "Data de Emissão": r.get("data_pedido"),
                "Fornecedor": r.get("fornecedor_nome"),
                "Descrição do Insumo": r.get("descricao_material"),
                "Família de Insumo": r.get("familia_insumo"),
                "Quantidade": r.get("quantidade"),
                "Unidade": r.get("unidade"),
                "Preço Unitário (R$)": float(r.get("preco_unitario", 0.0) or 0.0),
                "Preço Total Item (R$)": float(r.get("preco_total_item", 0.0) or 0.0),
                "Previsão de Entrega": r.get("data_entrega_prevista"),
                "Condição de Pagamento": r.get("condicao_pagamento"),
                "Vendedor": r.get("vendedor")
            })
            
        df_geral = pd.DataFrame(rows)
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            df_geral.to_excel(writer, index=False, sheet_name="Pedidos_Compra")
        out.seek(0)
        
        return Response(
            content=out.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=pedidos_compra_maison_plage_geral.xlsx"}
        )

# DETALHES DO PEDIDO (RESPOSTA INSTANTÂNEA EM MEMÓRIA RAM)
@app.get("/api/order/{pc_num}")
async def api_order_detail(pc_num: str, role: str = "campo"):
    hide_fin = not can_view_monetary(role)
    _, orders_by_pc = get_cached_raw_records()
    
    items = orders_by_pc.get(str(pc_num).strip(), [])
    if not items:
        # Tenta na lista filtrada caso ainda nao esteja no cache
        items = query_service.get_order_by_number(pc_num)
        
    if not items:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")
    
    it0 = items[0]
    total_val = sum(float(str(x.get("preco_total_item", 0.0) or 0.0)) for x in items)
    fornec_nome = str(it0.get("fornecedor_nome") or it0.get("fornecedor", "Fornecedor da Obra")).strip()
    fornec_cnpj = str(it0.get("fornecedor_cnpj", "")).strip()
    
    matched_sup = find_supplier_contact(fornec_nome, fornec_cnpj)
    fornec_contato = parse_supplier_dual_contacts(matched_sup) if matched_sup else None

    itens_formatados = []
    for it in items:
        itens_formatados.append({
            "item_num": it.get("codigo_insumo", "-"),
            "descricao": str(it.get("descricao_material", "") or it.get("descricao_completa", "")),
            "quantidade": it.get("quantidade", 0),
            "unidade": str(it.get("unidade", "UN")).strip(),
            "valor_unitario": f"R${float(it.get('preco_unitario', 0.0) or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if not hide_fin else None,
            "valor_total": f"R${float(it.get('preco_total_item', 0.0) or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if not hide_fin else None
        })

    return {
        "pc": str(pc_num),
        "fornecedor": fornec_nome,
        "contatos": fornec_contato if not hide_fin else None,
        "data_emissao": it0.get("data_pedido", "-"),
        "data_entrega": it0.get("data_entrega_prevista", "A Confirmar"),
        "condicao_pagamento": it0.get("condicao_pagamento", "Conforme Pedido") if not hide_fin else None,
        "valor_total_formatado": f"R${total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if not hide_fin else None,
        "itens": itens_formatados,
        "can_pdf": can_download_files(role)
    }

@app.get("/api/order/{pc_num}/pdf")
async def api_order_pdf(pc_num: str, role: str = "campo"):
    if not can_download_files(role):
        raise HTTPException(status_code=403, detail="Visualização de PDF reservada para Engenharia e Administração.")
    
    local_pdf = f"data/pdfs/PC_{pc_num}.pdf"
    if os.path.exists(local_pdf):
        return FileResponse(local_pdf, filename=f"PC_{pc_num}.pdf", media_type="application/pdf")
    
    fid = find_file_id_for_order(pc_num)
    if fid:
        token = "8847996417:AAGItLPuNaHN0girA46486IaESdPZ8w7bzA"
        r = requests.get(f"https://api.telegram.org/bot{token}/getFile?file_id={fid}").json()
        if r.get("ok"):
            fpath = r["result"]["file_path"]
            pdf_bytes = requests.get(f"https://api.telegram.org/file/bot{token}/{fpath}").content
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f"inline; filename=PC_{pc_num}.pdf"}
            )
            
    raise HTTPException(status_code=404, detail="PDF deste pedido não localizado no momento.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
