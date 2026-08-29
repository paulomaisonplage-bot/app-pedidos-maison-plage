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
from src.excel_manager import calculate_installments_for_item
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


def build_order_card_data(pc: str, role: str) -> Optional[dict]:
    hide_fin = (role == "campo")
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
        "can_pdf": (role in ["admin", "engenharia", "administracao"])
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
        c = build_order_card_data(pc, role)
        if c:
            cards.append(c)
    return {"offset": offset, "periodo": periodo_str, "cards": cards}

# 2. ENTREGAS DO MÊS
@app.get("/api/deliveries/month")
async def api_deliveries_month(mes: int = 8, ano: int = 2026, role: str = "campo"):
    hide_fin = (role == "campo")
    msg, pcs = query_service.get_delivery_summary_for_month(mes=mes, ano=ano, hide_financials=hide_fin, item_offset=0, page_size=100)
    cards = []
    for pc in pcs:
        c = build_order_card_data(pc, role)
        if c:
            cards.append(c)
    return {"mes": mes, "ano": ano, "cards": cards}

# 3. CATÁLOGO ALFABÉTICO COMPLETO A-Z DE INSUMOS
@app.get("/api/materials/catalog")
async def api_materials_catalog(q: Optional[str] = None, letter: Optional[str] = None):
    raw_dict = query_service.manager.load_existing_records()
    
    insumos_map = {}
    for r in raw_dict.values():
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

    # Ordena alfabeticamente A-Z
    sorted_items = sorted(insumos_map.values(), key=lambda x: x["nome"].upper())

    # Filtro por letra inicial
    if letter and letter.upper() != "TODOS":
        l_upper = letter.upper()
        sorted_items = [i for i in sorted_items if i["nome"].upper().startswith(l_upper)]

    # Filtro por texto de busca
    if q:
        q_l = q.lower().strip()
        sorted_items = [i for i in sorted_items if q_l in i["nome"].lower() or q_l in i["codigo"].lower() or q_l in i["familia"].lower()]

    result = []
    for it in sorted_items[:300]:
        qtd_fmt = f"{it['qtd_total']:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".").rstrip('0').rstrip(',')
        result.append({
            "nome": it["nome"],
            "codigo": it["codigo"],
            "familia": it["familia"],
            "unidade": it["unidade"],
            "qtd_formatada": f"{qtd_fmt} {it['unidade'].lower()}",
            "pedidos_count": len(it["pedidos"]),
            "pedidos": sorted(list(it["pedidos"]), reverse=True)
        })

    return {
        "total_cadastrados": len(insumos_map),
        "total_filtrados": len(sorted_items),
        "insumos": result
    }

@app.get("/api/materials/orders")
async def api_material_orders(nome: str, role: str = "campo"):
    hide_fin = (role == "campo")
    raw_dict = query_service.manager.load_existing_records()
    mat_upper = nome.upper().strip()
    
    # 1. Agrupa itens por PC na base inteira
    pc_items_map = {}
    for r in raw_dict.values():
        pc = str(r.get("numero_pedido", "")).strip()
        if not pc:
            continue
        if pc not in pc_items_map:
            pc_items_map[pc] = []
        pc_items_map[pc].append(r)
        
    matching_pcs = []
    for pc, items in pc_items_map.items():
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
            "can_pdf": (role in ["admin", "engenharia", "administracao"])
        })
        
    return {"material": nome, "total_pedidos": len(cards), "cards": cards}

# 4. GRUPOS DA OBRA
@app.get("/api/groups")
async def api_get_groups():
    families = query_service.get_all_families_summary()
    return {"groups": families}

# 5. COMPRAS RECENTES
@app.get("/api/recent_purchases")
async def api_recent_purchases(role: str = "campo"):
    hide_fin = (role == "campo")
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
    if role == "campo":
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

# 7. FLUXO FINANCEIRO INTELIGENTE
@app.get("/api/financial/summary")
async def api_financial_summary(role: str = "campo"):
    if role not in ["admin", "engenharia"]:
        raise HTTPException(status_code=403, detail="Acesso exclusivo para Engenharia e Administração.")
    
    records = query_service._get_all_records()
    total_contratado = sum(float(r.get("preco_total_item", 0.0) or 0.0) for r in records)
    
    # 1. Desembolso por Mês via Parcelas
    all_insts = []
    for r in records:
        all_insts.extend(calculate_installments_for_item(r))
        
    monthly_vals = {6: 0.0, 7: 0.0, 8: 0.0, 9: 0.0, 10: 0.0, 11: 0.0, 12: 0.0}
    month_names = {6: "Junho", 7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"}
    
    for i in all_insts:
        dt_venc = i.get("_venc_dt")
        val = float(i.get("valor_parcela", 0.0) or 0.0)
        if dt_venc and dt_venc.year == 2026 and dt_venc.month in monthly_vals:
            monthly_vals[dt_venc.month] += val

    val_ago = monthly_vals[8]
    val_futuro = sum(v for m, v in monthly_vals.items() if m >= 9)
    max_month_val = max(monthly_vals.values()) or 1.0

    bars = []
    for m in range(6, 13):
        v = monthly_vals[m]
        pct = (v / max_month_val) * 100
        bars.append({
            "mes_num": m,
            "mes_nome": month_names[m],
            "valor_fmt": f"R${v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "pct": round(pct, 1),
            "is_current": (m == 8)
        })

    # 2. Distribuição por Macro-Grupos
    MACRO_GROUPS = [
        {"name": "Obra Grossa & Estrutura", "icon": "🏗️", "sub": ["01 AGREGADOS", "02 ARTEFATOS", "03 BLOCOS", "15 MADEIRA", "18 MISTURAS", "20 PAVIMENTA", "23 PRODUTOS METALICOS", "34 ARGAMASSAS", "36 TELHAS", "39 VEDA"], "total": 0.0, "color": "#3b82f6"},
        {"name": "Instalações Prediais", "icon": "⚡", "sub": ["07 ENERGIA", "12 INSTAL.HIDRAULICA", "13 INSTALA", "14 LOU", "24 PVC", "28 INST. DE INCENDIO", "42 INST. DE REFRIGERA", "43 INST. DE G"], "total": 0.0, "color": "#10b981"},
        {"name": "Acabamentos & Pintura", "icon": "🛡️", "sub": ["11 IMPERMEABILIZANTE", "16 MATERIAL BETUMINOSO", "25 REVESTIMENTO", "29 FERRAGENS", "30 MOVEIS", "37 TINTAS", "19 PAISAGISMO", "38 URBANISMO"], "total": 0.0, "color": "#f59e0b"},
        {"name": "Segurança, EPIs & Apoio", "icon": "🦺", "sub": ["10 EPI", "33 MATERIAL DE LIMPEZA", "35 SINALIZA", "44 FERRAMENTAS", "45 COMBUSTIVEIS", "47 MATERIAL DE EXPEDIENTE", "04 DIVERSOS", "05 ALIMENTACAO", "21 PRODUTOS INDUSTRIALIZADOS"], "total": 0.0, "color": "#8b5cf6"},
        {"name": "Serviços & Equipamentos", "icon": "🚜", "sub": ["06 ALUGUEL", "08 ESQUADRIAS METALICAS", "26 SERVI", "31 ESQUADRIAS DE MADEIRA", "01 Equipamentos Aluguel", "02 Equipamentos", "01 Verbas", "02 Servi"], "total": 0.0, "color": "#ec4899"}
    ]

    for r in records:
        fam_raw = str(r.get("familia_insumo", "") or "").upper()
        val = float(r.get("preco_total_item", 0.0) or 0.0)
        alloc = False
        for g in MACRO_GROUPS:
            if any(t in fam_raw for t in g["sub"]):
                g["total"] += val
                alloc = True
                break
        if not alloc:
            MACRO_GROUPS[0]["total"] += val

    groups_res = []
    for g in MACRO_GROUPS:
        pct = (g["total"] / total_contratado * 100) if total_contratado > 0 else 0
        groups_res.append({
            "name": g["name"],
            "icon": g["icon"],
            "color": g["color"],
            "valor_fmt": f"R${g['total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "pct": round(pct, 1)
        })

    return {
        "kpis": {
            "total_contratado": f"R${total_contratado:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "mes_atual": f"R${val_ago:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "futuro": f"R${val_futuro:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        },
        "monthly_bars": bars,
        "macro_groups": groups_res
    }

# 8. EXPORTAR PLANILHAS EM EXCEL (.xlsx)
@app.get("/api/export/excel")
async def api_export_excel(tipo: str = "geral", role: str = "campo"):
    if role not in ["admin", "engenharia"]:
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

# DETALHES DO PEDIDO
@app.get("/api/order/{pc_num}")
async def api_order_detail(pc_num: str, role: str = "campo"):
    hide_fin = (role == "campo")
    items = query_service.get_order_by_number(pc_num)
    if not items:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    
    it0 = items[0]
    total_val = sum(float(str(x.get("preco_total_item", 0.0) or 0.0)) for x in items)
    fornec_nome = str(it0.get("fornecedor_nome") or it0.get("fornecedor", "Fornecedor da Obra")).strip()
    fornec_cnpj = str(it0.get("fornecedor_cnpj", "")).strip()
    
    # Busca contato estruturado do fornecedor com algoritmo inteligente
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
        "can_pdf": (role in ["admin", "engenharia", "administracao"])
    }

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
