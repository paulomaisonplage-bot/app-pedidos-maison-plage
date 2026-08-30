"""
Módulo de Controle de Acesso e Gestão de Perfis de Usuários (AuthService).

Perfis Suportados:
1. 'admin': Administrador Master (Você) - Acesso total + Aprovação e gestão de membros.
2. 'engenharia': Acesso completo a materiais, entregas, desembolso, valores em R$ e planilhas Excel.
3. 'suporte': Acesso operacional apenas a entregas, insumos, quantidades e fornecedores (SEM valores financeiros e SEM download de planilhas).
"""

import os
import json
import logging
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


DEFAULT_ADMIN_IDS = [8459937324]


class AuthService:
    def __init__(
        self,
        config_path: str = "data/usuarios_autorizados.json",
        gdrive_folder: str = r"G:\Meu Drive\Maison Plage - Pedidos de Compra\Configurações e Catálogos"
    ):
        self.config_path = os.path.abspath(config_path)
        self.gdrive_path = os.path.join(gdrive_folder, "usuarios_autorizados.json")
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        self._simulated_roles: Dict[int, str] = {}
        self._data = self._load_data()


    def _load_data(self) -> Dict[str, Any]:
        # Tenta carregar do Google Drive primeiro se existir
        for path in [self.gdrive_path, self.config_path]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if "admin_ids" in data and "users" in data:
                            for aid in DEFAULT_ADMIN_IDS:
                                if aid not in data["admin_ids"]:
                                    data["admin_ids"].append(aid)
                            if "8459937324" not in data["users"]:
                                data["users"]["8459937324"] = {
                                    "nome": "Paulo Lôbo",
                                    "username": "",
                                    "role": "admin",
                                    "data_autorizacao": "28/08/2026 20:00:00"
                                }
                            return data
                except Exception as e:
                    logger.warning(f"Falha ao ler {path}: {e}")

        # Padrão inicial com Paulo como Admin Master
        return {
            "admin_ids": list(DEFAULT_ADMIN_IDS),
            "users": {
                "8459937324": {
                    "nome": "Paulo Lôbo",
                    "username": "",
                    "role": "admin",
                    "data_autorizacao": "28/08/2026 20:00:00"
                }
            },
            "pending_requests": {}
        }

    def _save_data(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)

            # Espelha para o Google Drive se a pasta existir
            if os.path.exists(os.path.dirname(self.gdrive_path)):
                try:
                    shutil.copy2(self.config_path, self.gdrive_path)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Erro ao salvar usuários autorizados: {e}")

    def is_authorized(self, user_id: int) -> bool:
        if user_id in DEFAULT_ADMIN_IDS or user_id in self._data.get("admin_ids", []):
            return True
        uid_str = str(user_id)
    def is_authorized(self, user_id: int) -> bool:
        if user_id in DEFAULT_ADMIN_IDS or user_id in self._data.get("admin_ids", []):
            return True
        uid_str = str(user_id)
        user = self._data.get("users", {}).get(uid_str)
        return user is not None and user.get("role") in ["admin", "engenharia", "administracao", "adm", "campo", "almoxarifado", "mestre", "suporte"]

    def is_admin(self, user_id: int) -> bool:
        if user_id in DEFAULT_ADMIN_IDS or user_id in self._data.get("admin_ids", []):
            return True
        user = self._data.get("users", {}).get(str(user_id))
        return user is not None and user.get("role") == "admin"

    def get_user_role(self, user_id: int) -> str:
        if user_id in DEFAULT_ADMIN_IDS or user_id in self._data.get("admin_ids", []):
            return "admin"
        user = self._data.get("users", {}).get(str(user_id))
        if user:
            role = user.get("role", "campo")
            if role in ["almoxarifado", "adm", "administracao"]:
                return "administracao"
            elif role in ["mestre", "suporte", "campo"]:
                return "campo"
            return role
        return ""

    def set_simulated_role(self, user_id: int, role: Optional[str]) -> bool:
        """Permite que o Administrador Master simule outro perfil para teste."""
        if not self.is_admin(user_id):
            return False
        if not role or role == "admin":
            if user_id in self._simulated_roles:
                del self._simulated_roles[user_id]
        else:
            canonical_role = role.lower()
            if canonical_role in ["almoxarifado", "adm", "administracao"]:
                canonical_role = "administracao"
            elif canonical_role in ["mestre", "suporte", "campo"]:
                canonical_role = "campo"
            self._simulated_roles[user_id] = canonical_role
        return True

    def get_simulated_role(self, user_id: int) -> Optional[str]:
        return self._simulated_roles.get(user_id)

    def get_effective_role(self, user_id: int) -> str:
        """Retorna o perfil em vigor considerando a simulação ativa para o Admin."""
        if user_id in self._simulated_roles:
            return self._simulated_roles[user_id]
        return self.get_user_role(user_id)

    def can_view_financials(self, user_id: int) -> bool:
        """Permite visualizar o fluxo financeiro de desembolso (Admin e Engenharia)."""
        return self.get_effective_role(user_id) in ["admin", "engenharia"]

    def can_download_spreadsheets(self, user_id: int) -> bool:
        """Permite baixar arquivos e planilhas Excel (Admin e Engenharia)."""
        return self.get_effective_role(user_id) in ["admin", "engenharia"]

    def can_view_monetary_values(self, user_id: int) -> bool:
        """Permite visualizar valores em R$ nos pedidos e resumos (Admin, Engenharia e Administração)."""
        return self.get_effective_role(user_id) in ["admin", "engenharia", "administracao", "adm", "almoxarifado"]

    def can_download_pdfs(self, user_id: int) -> bool:
        """Permite baixar o PDF original do pedido de compra (Admin, Engenharia e Administração)."""
        return self.get_effective_role(user_id) in ["admin", "engenharia", "administracao", "adm", "almoxarifado"]

    def can_view_suppliers(self, user_id: int) -> bool:
        """Permite acessar o catálogo e contatos de fornecedores (Admin, Engenharia e Administração)."""
        return self.get_effective_role(user_id) in ["admin", "engenharia", "administracao", "adm", "almoxarifado"]

    def register_first_admin_if_empty(self, user_id: int, nome: str, username: str = "") -> bool:
        """Registra o primeiro usuário como Administrador Master se a lista de admins estiver vazia."""
        if not self._data.get("admin_ids"):
            self._data.setdefault("admin_ids", []).append(user_id)
            self._data.setdefault("users", {})[str(user_id)] = {
                "nome": nome,
                "username": username,
                "role": "admin",
                "data_autorizacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            }
            self._save_data()
            logger.info(f"Primeiro Administrador Master registrado: {nome} (ID: {user_id})")
            return True
        return False

    def add_pending_request(self, user_id: int, nome: str, username: str = ""):
        uid_str = str(user_id)
        self._data.setdefault("pending_requests", {})[uid_str] = {
            "nome": nome,
            "username": username,
            "data_solicitacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        }
        self._save_data()

    def authorize_user(self, user_id: int, nome: str, username: str, role: str) -> bool:
        canonical_role = role.lower()
        if canonical_role in ["almoxarifado", "adm", "administracao"]:
            canonical_role = "administracao"
        elif canonical_role in ["mestre", "suporte", "campo"]:
            canonical_role = "campo"

        if canonical_role not in ["admin", "engenharia", "administracao", "campo"]:
            return False

        uid_str = str(user_id)
        self._data.setdefault("users", {})[uid_str] = {
            "nome": nome,
            "username": username,
            "role": canonical_role,
            "data_autorizacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        }

        # Remove da lista de pendentes
        if "pending_requests" in self._data and uid_str in self._data["pending_requests"]:
            del self._data["pending_requests"][uid_str]

        self._save_data()
        logger.info(f"Usuário autorizado: {nome} (ID: {user_id}) com papel {canonical_role}")
        return True


    def revoke_user(self, user_id: int) -> bool:
        uid_str = str(user_id)
        if user_id in self._data.get("admin_ids", []):
            logger.warning("Tentativa de revogar Administrador Master negada.")
            return False

        if uid_str in self._data.get("users", {}):
            del self._data["users"][uid_str]
            self._save_data()
            logger.info(f"Acesso revogado para usuário ID: {user_id}")
            return True
        return False

    def get_all_users(self) -> Dict[str, Any]:
        return self._data.get("users", {})

    def get_admin_ids(self) -> List[int]:
        return self._data.get("admin_ids", [])
