import os
import re
import json
import requests
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.query_service import OrderQueryService, load_all_suppliers_contacts
from src.auth_service import AuthService

app = FastAPI(title="Maison Plage • App de Pedidos", version="2.2.20260829172549")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

EXCEL_PATH = os.getenv("EXCEL_PATH", "data/pedidos_compra_consolidado.xlsx")
if not os.path.exists(EXCEL_PATH) and os.path.exists("../data/pedidos_compra_consolidado.xlsx"):
    EXCEL_PATH = "../data/pedidos_compra_consolidado.xlsx"

USERS_FILE = "data/usuarios_autorizados.json"
query_service = OrderQueryService(EXCEL_PATH)
auth_service = AuthService(USERS_FILE)

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

# 1. ENTREGAS DA SEMANA
@app.get("/api/deliveries/week")
async def api_deliveries_week(offset: int = 0, role: str = "campo"):
    hide_fin = (role == "campo")
    msg, pcs = query_service.get_deliveries_summary_for_week(offset=offset, hide_financials=hide_fin, item_offset=0, page_size=100)
    
    hoje = date.today()
    segunda = hoje - timedelta(days=hoje.weekday()) + timedelta(weeks=offset)
    domingo = segunda + timedelta(days=6)
    periodo_str = f"{segunda.strftime('%d/%m')} a {domingo.strftime('%d/%m/%Y')}"

    cards = []
    for pc in pcs:
        items = query_service.get_order_by_number(pc)
        if items:
            it0 = items[0]
            total_val = sum(float(str(x.get("preco_total_item", 0.0) or 0.0)) for x in items)
            fornec = str(it0.get("fornecedor_nome") or it0.get("fornecedor", "Fornecedor da Obra")).strip()
            desc = str(it0.get("descricao_material", "") or it0.get("descricao_completa", "Diversos")).strip()
            cards.append({
                "pc": str(pc),
                "fornecedor": fornec,
                "data_entrega": it0.get("data_entrega_prevista", "A Confirmar"),
                "total_itens": len(items),
                "descricao_resumo": desc,
                "valor_total_formatado": f"R${total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if not hide_fin else None,
                "can_pdf": (role in ["admin", "engenharia", "administracao"])
            })
    return {"offset": offset, "periodo": periodo_str, "cards": cards}

# 2. ENTREGAS DO MÊS
@app.get("/api/deliveries/month")
async def api_deliveries_month(mes: int = 8, ano: int = 2026, role: str = "campo"):
    hide_fin = (role == "campo")
    msg, pcs = query_service.get_delivery_summary_for_month(mes=mes, ano=ano, hide_financials=hide_fin, item_offset=0, page_size=100)
    cards = []
    for pc in pcs:
        items = query_service.get_order_by_number(pc)
        if items:
            it0 = items[0]
            total_val = sum(float(str(x.get("preco_total_item", 0.0) or 0.0)) for x in items)
            fornec = str(it0.get("fornecedor_nome") or it0.get("fornecedor", "Fornecedor da Obra")).strip()
            desc = str(it0.get("descricao_material", "") or it0.get("descricao_completa", "Diversos")).strip()
            cards.append({
                "pc": str(pc),
                "fornecedor": fornec,
                "data_entrega": it0.get("data_entrega_prevista", "A Confirmar"),
                "total_itens": len(items),
                "descricao_resumo": desc,
                "valor_total_formatado": f"R${total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if not hide_fin else None
            })
    return {"mes": mes, "ano": ano, "cards": cards}

# 3. BUSCA DE INSUMOS
@app.get("/api/materials/search")
async def api_search_materials(q: str, role: str = "campo"):
    hide_fin = (role == "campo")
    msg, pcs = query_service.search_materials_for_site(q, hide_financials=hide_fin, item_offset=0, page_size=50)
    cards = []
    for pc in pcs:
        items = query_service.get_order_by_number(pc)
        if items:
            it0 = items[0]
            fornec = str(it0.get("fornecedor_nome") or it0.get("fornecedor", "Fornecedor da Obra")).strip()
            matched = [x for x in items if q.lower() in str(x.get("descricao_material", "")).lower() or q.lower() in str(x.get("descricao_completa", "")).lower()]
            cards.append({
                "pc": str(pc),
                "fornecedor": fornec,
                "data_entrega": it0.get("data_entrega_prevista", "-"),
                "matched_items": [f"{m.get('quantidade')} {m.get('unidade', 'UN')} - {m.get('descricao_material', '') or m.get('descricao_completa', '')}" for m in matched[:3]]
            })
    return {"query": q, "results": cards}

# 4. GRUPOS DA OBRA
@app.get("/api/groups")
async def api_get_groups():
    families = query_service.get_all_families_summary()
    return {"groups": families}

# 5. COMPRAS RECENTES
@app.get("/api/orders/recent")
async def api_recent_orders(role: str = "campo"):
    hide_fin = (role == "campo")
    msg, pcs = query_service.get_recent_orders_summary(max_orders=30, hide_financials=hide_fin, item_offset=0, page_size=30)
    cards = []
    for pc in pcs:
        items = query_service.get_order_by_number(pc)
        if items:
            it0 = items[0]
            total_val = sum(float(str(x.get("preco_total_item", 0.0) or 0.0)) for x in items)
            fornec = str(it0.get("fornecedor_nome") or it0.get("fornecedor", "Fornecedor da Obra")).strip()
            desc = str(it0.get("descricao_material", "") or it0.get("descricao_completa", "Diversos")).strip()
            cards.append({
                "pc": str(pc),
                "fornecedor": fornec,
                "data_emissao": it0.get("data_pedido", "-"),
                "data_entrega": it0.get("data_entrega_prevista", "-"),
                "total_itens": len(items),
                "descricao_resumo": desc,
                "valor_total_formatado": f"R${total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if not hide_fin else None
            })
    return {"cards": cards}

# 6. FORNECEDORES
@app.get("/api/suppliers")
async def api_suppliers(q: Optional[str] = None, role: str = "campo"):
    if role == "campo":
        raise HTTPException(status_code=403, detail="Acesso reservado para Engenharia e Administração")
    
    catalog = load_all_suppliers_contacts()
    if q:
        clean_q = re.sub(r'[^\\w\\s]', ' ', q).lower().strip()
        tokens = [t for t in clean_q.split() if len(t) >= 2]
        catalog = [
            f for f in catalog
            if all(t in f["nome"].lower() or t in f.get("vendedor", "").lower() or t in f.get("email", "").lower() for t in tokens)
        ]
    
    fornecs = []
    for f in catalog:
        tel = str(f.get("telefone", "") or "").strip()
        clean_tel = re.sub(r'[^0-9]', '', tel)
        fornecs.append({
            "razao_social": f.get("nome", "Não Informado"),
            "telefone": tel if tel else "Não Informado",
            "telefone_clean": clean_tel,
            "email": f.get("email", "Não Informado"),
            "contato_vendedor": f.get("vendedor", "-")
        })

    return {"suppliers": fornecs}

# 7. FLUXO FINANCEIRO
@app.get("/api/financial/summary")
async def api_financial_summary(role: str = "campo"):
    if role not in ["admin", "engenharia"]:
        raise HTTPException(status_code=403, detail="Acesso exclusivo para Engenharia")
    resumo = query_service.get_financial_schedule_summary()
    return {"summary_text": resumo}

# 8. EXPORTAR PLANILHA EXCEL
@app.get("/api/export/excel")
async def api_export_excel(role: str = "campo"):
    if role not in ["admin", "engenharia"]:
        raise HTTPException(status_code=403, detail="Download reservado para Engenharia.")
    if os.path.exists(EXCEL_PATH):
        return FileResponse(
            EXCEL_PATH,
            filename="pedidos_compra_maison_plage.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=pedidos_compra_maison_plage.xlsx"}
        )
    raise HTTPException(status_code=404, detail="Planilha não encontrada.")

# DETALHES DO PEDIDO
@app.get("/api/order/{pc_num}")
async def api_order_detail(pc_num: str, role: str = "campo"):
    hide_fin = (role == "campo")
    items = query_service.get_order_by_number(pc_num)
    if not items:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    
    it0 = items[0]
    total_val = sum(float(str(x.get("preco_total_item", 0.0) or 0.0)) for x in items)
    fornec = str(it0.get("fornecedor_nome") or it0.get("fornecedor", "Fornecedor da Obra")).strip()
    
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
        "fornecedor": fornec,
        "data_emissao": it0.get("data_pedido", "-"),
        "data_entrega": it0.get("data_entrega_prevista", "A Confirmar"),
        "condicao_pagamento": it0.get("condicao_pagamento", "Conforme Pedido") if not hide_fin else None,
        "valor_total_formatado": f"R${total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if not hide_fin else None,
        "itens": itens_formatados,
        "can_pdf": (role in ["admin", "engenharia", "administracao"])
    }

# VISUALIZADOR E DOWNLOAD DE PDF ORIGINAL
@app.get("/api/order/{pc_num}/pdf")
async def api_order_pdf(pc_num: str, role: str = "campo"):
    if role == "campo":
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
