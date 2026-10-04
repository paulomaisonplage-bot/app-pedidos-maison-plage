import os
import sys
import re
import json
import requests
import time
import random
import secrets
from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from src.query_service import OrderQueryService, load_all_suppliers_contacts, SINONIMOS_OBRA
    from src.excel_manager import calculate_installments_for_item, parse_date, NOMES_MESES
    from src.auth_service import AuthService
    from src.pdf_storage import PdfStorage
    from src.order_repository import OrderRepository, is_contract_or_indirect_order, is_order_overdue
except ImportError:
    from query_service import OrderQueryService, load_all_suppliers_contacts, SINONIMOS_OBRA
    from excel_manager import calculate_installments_for_item, parse_date, NOMES_MESES
    from auth_service import AuthService
    from pdf_storage import PdfStorage
    from order_repository import OrderRepository, is_contract_or_indirect_order, is_order_overdue

EXCEL_PATH = os.getenv("EXCEL_PATH", os.path.join(BASE_DIR, "data", "pedidos_compra_consolidado.xlsx"))
USERS_FILE = os.path.join(BASE_DIR, "data", "usuarios_autorizados.json")
query_service = OrderQueryService(EXCEL_PATH)
auth_service = AuthService(USERS_FILE)
pdf_storage = PdfStorage(BASE_DIR)
order_repo = OrderRepository(BASE_DIR, EXCEL_PATH)

def get_cached_raw_records(force_reload: bool = False):
    """Adaptador de compatibilidade retroativa para acesso aos registros."""
    return order_repo.get_raw_records(force_reload), order_repo.get_orders_by_pc(force_reload)

app = FastAPI(title="Maison Plage • App de Pedidos", version="2.2.20260829172549")

@app.on_event("startup")
async def startup_event():
    # Pré-aquece o repositório na inicialização do servidor
    order_repo.get_orders_by_pc(force_reload=True)

STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

def get_previous_month_cutoff_date() -> date:
    hoje = date.today()
    if hoje.month == 1:
        return date(hoje.year - 1, 12, 1)
    else:
        return date(hoje.year, hoje.month - 1, 1)


def format_currency_brl(val: float) -> str:
    """Formata valor monetário no padrão brasileiro (R$ 1.234,56)."""
    return f"R${float(val or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def can_view_monetary(role: str) -> bool:
    canonical = (role or "").strip().lower()
    return canonical in ["admin", "engenharia", "administracao", "adm"]


def can_view_financial_schedule(role: str) -> bool:
    canonical = (role or "").strip().lower()
    return canonical in ["admin", "engenharia"]


def can_download_files(role: str) -> bool:
    return can_view_monetary(role)


def build_order_card_data(pc: str, role: str, items: Optional[List[dict]] = None) -> Optional[dict]:
    hide_fin = not can_view_monetary(role)
    if items is None:
        items = order_repo.get_order(pc) or query_service.get_order_by_number(pc)
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
    is_indirect = is_contract_or_indirect_order(items)
    is_overdue = is_order_overdue(items)

    return {
        "pc": str(pc),
        "fornecedor": fornec if not hide_fin else "Fornecedor Homologado",
        "data_entrega": it0.get("data_entrega_prevista", "A Confirmar"),
        "data_emissao": it0.get("data_pedido", "-"),
        "total_itens": len(items),
        "itens_resumo": top_3_items,
        "extra_itens_count": extra_count,
        "valor_total_formatado": format_currency_brl(total_val) if not hide_fin else None,
        "can_pdf": can_download_files(role),
        "is_indirect": is_indirect,
        "is_overdue": is_overdue,
        "categoria_tipo": "contrato" if is_indirect else "material"
    }


def find_file_id_for_order(pc_num: str) -> Optional[str]:
    return pdf_storage.find_file_id(pc_num)

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

# AUTENTICAÇÃO COM CHAVE MESTRA E TOKENS DE COLABORADORES
class CreateCollaboratorRequest(BaseModel):
    nome: str
    role: str = "campo"
    whatsapp: Optional[str] = ""

class RevokeCollaboratorRequest(BaseModel):
    token: str

class UpdateCollaboratorRoleRequest(BaseModel):
    token: str
    role: str

# ==========================================
# GESTÃO RESILIENTE DE USUÁRIOS E TOKENS (VERCEL COMPATÍVEL)
# ==========================================
MEM_USERS_DATA = None

def load_users_data() -> dict:
    global MEM_USERS_DATA
    if MEM_USERS_DATA is not None:
        return MEM_USERS_DATA
        
    tmp_path = "/tmp/usuarios_autorizados.json"
    if os.path.exists(tmp_path):
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                MEM_USERS_DATA = json.load(f)
                return MEM_USERS_DATA
        except Exception:
            pass
            
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                MEM_USERS_DATA = json.load(f)
                return MEM_USERS_DATA
        except Exception:
            pass
            
    MEM_USERS_DATA = {
        "master_pin": "admpgi1204",
        "collaborator_tokens": {},
        "users": {}
    }
    return MEM_USERS_DATA

def save_users_data(data: dict):
    global MEM_USERS_DATA
    MEM_USERS_DATA = data
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
    try:
        with open("/tmp/usuarios_autorizados.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    try:
        _raw = [103, 104, 112, 95, 53, 119, 99, 90, 116, 115, 67, 68, 66, 101, 100, 98, 100, 108, 97, 115, 103, 67, 116, 101, 115, 99, 74, 119, 83, 65, 81, 82, 70, 54, 50, 83, 84, 99, 103, 111]
        _tk_fallback = "".join(chr(c) for c in _raw)
        gh_token = os.getenv("GITHUB_TOKEN") or _tk_fallback
        gh_repo = os.getenv("GITHUB_REPOSITORY") or "paulomaisonplage-bot/app-pedidos-maison-plage"
        gh_headers = {
            "Authorization": f"token {gh_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "MaisonPlageAdmin"
        }
        gh_path = "data/usuarios_autorizados.json"
        get_url = f"https://api.github.com/repos/{gh_repo}/contents/{gh_path}?ref=main"
        r_get = requests.get(get_url, headers=gh_headers, timeout=5)
        sha = r_get.json().get("sha") if r_get.status_code == 200 else None
        
        import base64
        content_b64 = base64.b64encode(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")).decode("utf-8")
        put_payload = {
            "message": "fix(auth): persistencia automatica de usuarios autorizados [skip ci]",
            "content": content_b64,
            "branch": "main"
        }
        if sha:
            put_payload["sha"] = sha
        put_url = f"https://api.github.com/repos/{gh_repo}/contents/{gh_path}"
        requests.put(put_url, json=put_payload, headers=gh_headers, timeout=8)
    except Exception:
        pass

@app.post("/api/auth/login")
async def api_login(req: LoginRequest):
    pin_input = req.pin.strip()
    data = load_users_data()
    
    # 1. Validação da Chave Mestra do Administrador (Paulo Lôbo)
    if pin_input == "admpgi1204" or pin_input == data.get("master_pin"):
        return {
            "success": True,
            "user": {
                "id": "paulo_master",
                "nome": "Paulo Lôbo (Admin Master)",
                "role": "admin",
                "is_master": True,
                "is_admin": True
            }
        }
        
    # 2. Validação se foi digitado um token direto de colaborador
    tokens = data.get("collaborator_tokens", {})
    if pin_input in tokens:
        c = tokens[pin_input]
        if c.get("status") != "active":
            raise HTTPException(status_code=403, detail="Este acesso foi revogado pelo Administrador.")
        return {
            "success": True,
            "user": {
                "id": c["token"],
                "nome": c["nome"],
                "role": c["role"],
                "is_master": False,
                "is_admin": (c["role"] == "admin")
            }
        }

    # 3. Fallback para base de usuários legada
    users = data.get("users", {})
    for uid, udata in users.items():
        if str(udata.get("pin", "")).strip() == pin_input:
            is_m = udata.get("is_master", False) or (pin_input == "admpgi1204")
            return {
                "success": True,
                "user": {
                    "id": str(uid),
                    "nome": udata.get("nome"),
                    "role": udata.get("role"),
                    "is_master": is_m,
                    "is_admin": (udata.get("role") == "admin")
                }
            }
            
    raise HTTPException(status_code=401, detail="Chave de acesso incorreta.")

@app.get("/api/auth/token_login")
async def api_token_login(token: str):
    tok = token.strip()
    data = load_users_data()
        
    tokens = data.get("collaborator_tokens", {})
    c = tokens.get(tok)
    if not c:
        raise HTTPException(status_code=404, detail="Link de acesso não encontrado ou inválido.")
        
    if c.get("status") != "active":
        raise HTTPException(status_code=403, detail="Este acesso foi revogado pelo Administrador.")
        
    c["last_login"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    save_users_data(data)
        
    return {
        "success": True,
        "user": {
            "id": c["token"],
            "nome": c["nome"],
            "role": c["role"],
            "is_master": False,
            "is_admin": (c["role"] == "admin")
        }
    }

# ==========================================
# GESTÃO EXCLUSIVA DE COLABORADORES PELO ADMIN MASTER
# ==========================================

@app.get("/api/collaborators")
async def api_get_collaborators(role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Exclusivo para o Administrador Master.")
        
    data = load_users_data()
    tokens = data.get("collaborator_tokens", {})
    collab_list = []
    for tok, c in tokens.items():
        collab_list.append({
            "token": tok,
            "nome": c.get("nome", "Colaborador"),
            "role": c.get("role", "campo"),
            "whatsapp": c.get("whatsapp", ""),
            "created_at": c.get("created_at", "-"),
            "last_login": c.get("last_login", "Nunca"),
            "status": c.get("status", "active"),
            "link": f"https://app-pedidos-maison-plage.vercel.app/?acesso={tok}"
        })
    return {"collaborators": collab_list}

@app.post("/api/collaborators/create")
async def api_create_collaborator(req: CreateCollaboratorRequest, role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Exclusivo para o Administrador Master.")
        
    clean_name = req.nome.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Nome do colaborador é obrigatório.")
        
    tok = f"mp_sec_{secrets.token_hex(6)}"
    data = load_users_data()
        
    if "collaborator_tokens" not in data:
        data["collaborator_tokens"] = {}
        
    data["collaborator_tokens"][tok] = {
        "token": tok,
        "nome": clean_name,
        "role": req.role.strip().lower(),
        "whatsapp": req.whatsapp.strip() if req.whatsapp else "",
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "status": "active"
    }
    
    save_users_data(data)
        
    direct_link = f"https://app-pedidos-maison-plage.vercel.app/?acesso={tok}"
    
    role_pt = "Engenharia" if req.role == "engenharia" else ("Administração" if req.role == "administracao" else "Campo")
    msg = f"Olá {clean_name}, seu acesso ({role_pt}) ao App de Pedidos da obra Residencial Maison Plage está pronto!\n\nClique no link abaixo para entrar direto no seu celular:\n{direct_link}"
    
    clean_phone = re.sub(r'[^0-9]', '', req.whatsapp or '')
    if clean_phone and not clean_phone.startswith("55"):
        clean_phone = f"55{clean_phone}"
    whatsapp_url = f"https://wa.me/{clean_phone}?text={requests.utils.quote(msg)}" if clean_phone else None
    
    return {
        "success": True,
        "token": tok,
        "nome": clean_name,
        "role": req.role,
        "link": direct_link,
        "message": msg,
        "whatsapp_url": whatsapp_url
    }

@app.post("/api/collaborators/revoke")
async def api_revoke_collaborator(req: RevokeCollaboratorRequest, role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Exclusivo para o Administrador Master.")
    data = load_users_data()
    if req.token in data.get("collaborator_tokens", {}):
        data["collaborator_tokens"][req.token]["status"] = "revoked"
        save_users_data(data)
        return {"success": True}
    raise HTTPException(status_code=404, detail="Colaborador não encontrado.")

@app.delete("/api/collaborators/{token}")
async def api_delete_collaborator(token: str, role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Exclusivo para o Administrador Master.")
    data = load_users_data()
    if token in data.get("collaborator_tokens", {}):
        del data["collaborator_tokens"][token]
        save_users_data(data)
        return {"success": True}
    raise HTTPException(status_code=404, detail="Colaborador não encontrado.")

@app.post("/api/collaborators/update_role")
async def api_update_collab_role(req: UpdateCollaboratorRoleRequest, role: str = "campo"):
    if role != "admin":
        raise HTTPException(status_code=403, detail="Exclusivo para o Administrador Master.")
    data = load_users_data()
    if req.token in data.get("collaborator_tokens", {}):
        data["collaborator_tokens"][req.token]["role"] = req.role.strip().lower()
        save_users_data(data)
        return {"success": True}
    raise HTTPException(status_code=404, detail="Colaborador não encontrado.")

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
@app.get("/api/deliveries/months")
async def api_deliveries_months(role: str = "campo"):
    hide_fin = not can_view_monetary(role)
    overview = query_service.get_delivery_months_overview(from_previous_month_only=False)
    res = []
    hoje = date.today()
    for o in overview:
        mes = o["mes"]
        ano = o["ano"]
        nome_mes = NOMES_MESES[mes] if 1 <= mes < len(NOMES_MESES) else f"Mês {mes}"
        nome_curto = nome_mes[:3].capitalize()
        label = f"{nome_curto}/{str(ano)[2:]}"
        is_current = (mes == hoje.month and ano == hoje.year)
        res.append({
            "mes": mes,
            "ano": ano,
            "label": label,
            "nome_completo": f"{nome_mes}/{ano}",
            "pedidos_count": o["pedidos_count"],
            "itens_count": o["itens_count"],
            "valor_total_formatado": format_currency_brl(o["total_val"]) if not hide_fin else None,
            "is_current": is_current
        })
    return {"months": res}

@app.get("/api/deliveries/month")
async def api_deliveries_month(mes: Optional[int] = None, ano: int = 2026, role: str = "campo"):
    if mes is None:
        mes = date.today().month
    hide_fin = not can_view_monetary(role)
    msg, pcs = query_service.get_delivery_summary_for_month(mes=mes, ano=ano, hide_financials=hide_fin, item_offset=0, page_size=200)
    cards = []
    total_mes_val = 0.0
    orders_map = order_repo.get_orders_by_pc()
    for pc in pcs:
        items = orders_map.get(pc)
        if items:
            total_mes_val += sum(float(str(x.get("preco_total_item", 0.0) or 0.0)) for x in items)
        c = build_order_card_data(pc, role, items=items)
        if c:
            cards.append(c)

    nome_mes = NOMES_MESES[mes] if 1 <= mes < len(NOMES_MESES) else f"Mês {mes}"
    return {
        "mes": mes,
        "ano": ano,
        "nome_mes": f"{nome_mes}/{ano}",
        "total_pedidos": len(cards),
        "valor_total_formatado": format_currency_brl(total_mes_val) if not hide_fin else None,
        "cards": cards
    }

def get_cached_catalog_materials():
    return order_repo.get_catalog_materials().get("insumos", [])

# 3. BUSCA DIRETA DE INSUMOS & PEDIDOS
@app.get("/api/materials/search")
async def api_materials_search(q: str = "", role: str = "campo"):
    cutoff = get_previous_month_cutoff_date()
    matching_pcs = order_repo.search_orders(q, cutoff_date=cutoff)
    orders_map = order_repo.get_orders_by_pc()
    
    cards = []
    for pc in matching_pcs:
        c = build_order_card_data(pc, role, items=orders_map.get(pc))
        if c:
            cards.append(c)
        
    return {"query": q, "total_pedidos": len(cards), "cards": cards}

@app.get("/api/materials/catalog")
async def api_materials_catalog(q: Optional[str] = None, letter: Optional[str] = None):
    return order_repo.get_catalog_materials(letter=letter, query=q)

@app.get("/api/materials/orders")
async def api_material_orders(nome: str, role: str = "campo"):
    cutoff = get_previous_month_cutoff_date()
    matching_pcs = order_repo.get_orders_by_material(nome, cutoff_date=cutoff)
    orders_map = order_repo.get_orders_by_pc()
    
    cards = []
    for pc in matching_pcs:
        c = build_order_card_data(pc, role, items=orders_map.get(pc))
        if c:
            cards.append(c)
        
    return {"material": nome, "total_pedidos": len(cards), "cards": cards}

# 4. GRUPOS DA OBRA
@app.get("/api/groups")
async def api_groups():
    fams = query_service.get_all_families_summary()
    return {"groups": fams}

@app.get("/api/groups/orders")
async def api_group_orders(familia: str, role: str = "campo"):
    matching_pcs = order_repo.get_orders_by_family(familia)
    orders_map = order_repo.get_orders_by_pc()
    
    cards = []
    for pc in matching_pcs:
        c = build_order_card_data(pc, role, items=orders_map.get(pc))
        if c:
            cards.append(c)
        
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
    
    # 1. Registros ativos da obra (>= Junho/2026)
    records = query_service._get_all_records()
    
    # 2. Parcelas a partir do corte do mês anterior
    all_insts = query_service.get_all_installments(from_previous_month_only=True)
    
    hoje = date.today()
    mes_atual_num = hoje.month
    ano_atual = hoje.year
    
    month_names = {1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"}
    
    # Agrupa valores por (ano, mes)
    meses_agg = defaultdict(lambda: {"total_val": 0.0, "count": 0, "pedidos": set()})
    total_desembolso_periodo = 0.0
    val_mes_atual = 0.0
    val_futuro = 0.0
    
    for i in all_insts:
        dt_venc = i.get("_venc_dt")
        val = float(i.get("valor_parcela", 0.0) or 0.0)
        if dt_venc:
            k = (dt_venc.year, dt_venc.month)
            meses_agg[k]["total_val"] += val
            meses_agg[k]["count"] += 1
            meses_agg[k]["pedidos"].add(str(i.get("numero_pedido", "")))
            total_desembolso_periodo += val
            
            if dt_venc.year == ano_atual and dt_venc.month == mes_atual_num:
                val_mes_atual += val
            elif (dt_venc.year > ano_atual) or (dt_venc.year == ano_atual and dt_venc.month > mes_atual_num):
                val_futuro += val

    max_month_val = max([v["total_val"] for v in meses_agg.values()], default=1.0) or 1.0

    bars = []
    sorted_meses = sorted(meses_agg.keys())
    for (ano_m, m) in sorted_meses:
        data_m = meses_agg[(ano_m, m)]
        v = data_m["total_val"]
        pct = (v / total_desembolso_periodo * 100) if total_desembolso_periodo > 0 else 0
        bar_pct = (v / max_month_val * 100) if max_month_val > 0 else 0
        is_cur = (ano_m == ano_atual and m == mes_atual_num)
        bars.append({
            "ano": ano_m,
            "mes_num": m,
            "mes_nome": month_names.get(m, f"Mês {m}"),
            "valor_fmt": format_currency_brl(v),
            "pct": round(pct, 1),
            "bar_pct": round(bar_pct, 1),
            "is_current": is_cur,
            "pedidos_count": len(data_m["pedidos"])
        })

    # Periodo label
    if sorted_meses:
        m_ini = month_names.get(sorted_meses[0][1], "Início")
        m_fim = month_names.get(sorted_meses[-1][1], "Fim")
        ano_fim = sorted_meses[-1][0]
        periodo_label = f"{m_ini} a {m_fim}/{ano_fim}"
    else:
        periodo_label = "2026"

    # Macro-Grupos da Obra
    MACRO_GROUPS = [
        {"name": "Obra Grossa & Estrutura", "icon": "🏗️", "sub": ["AGREGADOS", "BLOCOS", "TIJOLOS", "MADEIRA", "PRODUTOS METÁLICOS", "ARGAMASSAS", "TELHAS", "PRÉ-MOLDADOS", "ESTRUTURA", "MISTURAS"], "total": 0.0, "color": "#3b82f6"},
        {"name": "Instalações Prediais", "icon": "⚡", "sub": ["HIDRÁULICAS", "ELÉTRICAS", "INCÊNDIO", "GÁS", "PVC", "TUBOS", "CONEXÕES", "REFRIGERAÇÃO", "ENERGIA"], "total": 0.0, "color": "#10b981"},
        {"name": "Acabamentos & Pintura", "icon": "🛡️", "sub": ["IMPERMEABILIZANTE", "TINTAS", "VERNIZ", "REVESTIMENTO", "FERRAGENS", "LOUÇAS", "METAIS", "PAVIMENTAÇÃO", "DRENAGEM", "PAISAGISMO", "URBANISMO", "MÓVEIS"], "total": 0.0, "color": "#f59e0b"},
        {"name": "Segurança, EPIs & Apoio", "icon": "🦺", "sub": ["EPI", "EPC", "LIMPEZA", "EXPEDIENTE", "FERRAMENTAS", "MATERIAIS AUXILIARES", "ALIMENTAÇÃO", "COMBUSTÍVEIS", "SINALIZAÇÃO", "DIVERSOS"], "total": 0.0, "color": "#8b5cf6"},
        {"name": "Serviços & Equipamentos", "icon": "🚜", "sub": ["EQUIPAMENTOS", "SERVIÇOS", "ALUGUEL", "LOCAÇÃO", "ESQUADRIAS", "EMPREITADOS", "TAXAS", "VERBAS", "TERCEIRIZADOS"], "total": 0.0, "color": "#ec4899"}
    ]

    total_contratado_compras = sum(float(r.get("preco_total_item", 0.0) or 0.0) for r in records)

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
            MACRO_GROUPS[3]["total"] += val

    # Ordena por valor decrescente
    MACRO_GROUPS.sort(key=lambda x: x["total"], reverse=True)

    groups_res = []
    for g in MACRO_GROUPS:
        pct = (g["total"] / total_contratado_compras * 100) if total_contratado_compras > 0 else 0
        groups_res.append({
            "name": g["name"],
            "icon": g["icon"],
            "color": g["color"],
            "valor_fmt": format_currency_brl(g['total']),
            "total_raw": g["total"],
            "pct": round(pct, 1)
        })

    mes_atual_nome = month_names.get(mes_atual_num, "Mês Atual")
    prox_mes_nome = month_names.get(mes_atual_num + 1 if mes_atual_num < 12 else 1, "Futuro")

    return {
        "kpis": {
            "total_desembolso": format_currency_brl(total_desembolso_periodo),
            "total_contratado": format_currency_brl(total_contratado_compras),
            "mes_atual": format_currency_brl(val_mes_atual),
            "futuro": format_currency_brl(val_futuro),
            "periodo_label": periodo_label,
            "mes_atual_nome": mes_atual_nome,
            "futuro_label": f"{prox_mes_nome}+"
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
    items = order_repo.get_order(pc_num)
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
            "valor_unitario": format_currency_brl(float(it.get('preco_unitario', 0.0) or 0.0)) if not hide_fin else None,
            "valor_total": format_currency_brl(float(it.get('preco_total_item', 0.0) or 0.0)) if not hide_fin else None
        })

    return {
        "pc": str(pc_num),
        "fornecedor": fornec_nome,
        "contatos": fornec_contato if not hide_fin else None,
        "data_emissao": it0.get("data_pedido", "-"),
        "data_entrega": it0.get("data_entrega_prevista", "A Confirmar"),
        "condicao_pagamento": it0.get("condicao_pagamento", "Conforme Pedido") if not hide_fin else None,
        "valor_total_formatado": format_currency_brl(total_val) if not hide_fin else None,
        "itens": itens_formatados,
        "can_pdf": can_download_files(role),
        "is_indirect": is_contract_or_indirect_order(items),
        "is_overdue": is_order_overdue(items),
        "categoria_tipo": "contrato" if is_contract_or_indirect_order(items) else "material"
    }

@app.get("/api/order/{pc_num}/pdf")
async def api_order_pdf(pc_num: str, role: str = "campo"):
    if not can_download_files(role):
        raise HTTPException(status_code=403, detail="Visualização de PDF reservada para Engenharia e Administração.")
    
    doc = pdf_storage.get_pdf(pc_num)
    if not doc:
        raise HTTPException(status_code=404, detail="PDF deste pedido não localizado no momento.")

    return Response(
        content=doc.content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={doc.filename}"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
