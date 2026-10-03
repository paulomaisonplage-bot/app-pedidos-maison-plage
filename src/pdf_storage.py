"""
Módulo Profundo de Armazenamento e Recuperação de PDFs de Pedidos de Compra (PdfStorage).
Segue os princípios da metodologia 'codebase-design':
- Interface Enxuta (Small Interface): get_pdf(pc_num) -> Optional[PdfDocument]
- Implementação Profunda (Deep Implementation): Busca local em disco com fallback inteligente para Telegram Cloud Bot.
- Seam Limpa: Isola completamente detalhes de HTTP, Telegram API e arquivos locais das rotas da aplicação.
"""

import os
import re
import glob
import json
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
import requests

logger = logging.getLogger(__name__)

DEFAULT_TELEGRAM_TOKEN = "8847996417:AAGItLPuNaHN0girA46486IaESdPZ8w7bzA"
DEFAULT_CHAT_ID = "8459937324"


@dataclass
class PdfDocument:
    content: bytes
    filename: str
    source: str  # "local" ou "telegram"


class PdfStorage:
    def __init__(
        self,
        base_dir: Optional[str] = None,
        telegram_token: str = DEFAULT_TELEGRAM_TOKEN,
        timeout: int = 25
    ):
        if base_dir is None:
            self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        else:
            self.base_dir = os.path.abspath(base_dir)

        self.telegram_token = telegram_token
        self.timeout = timeout
        self._links_cache: Optional[Dict[str, str]] = None
        self._links_mtime: float = 0

    # ---------------------------------------------------------
    # INTERFACE EXTERNA (O que os chamadores utilizam)
    # ---------------------------------------------------------

    def get_pdf(self, pc_num: str) -> Optional[PdfDocument]:
        """
        Recupera o documento PDF de um Pedido de Compra.
        Tenta primeiro no sistema de arquivos local (rápido em dev).
        Se não encontrar, busca transparentemente no Telegram Bot Cloud (Vercel).
        """
        clean_pc = str(pc_num).strip()
        if not clean_pc:
            return None

        # 1. Tenta carregar do disco local
        local_doc = self._load_from_local(clean_pc)
        if local_doc:
            return local_doc

        # 2. Tenta carregar do Telegram Cloud Storage
        cloud_doc = self._load_from_telegram(clean_pc)
        if cloud_doc:
            return cloud_doc

        return None

    def find_file_id(self, pc_num: str) -> Optional[str]:
        """Localiza o file_id do Telegram associado ao pedido."""
        links = self._get_links_map()
        pc_clean = str(pc_num).strip().lstrip("0")
        pattern = re.compile(rf"^PedidoCompra0*{pc_clean}[_.]|^PC_?0*{pc_clean}[_.]", re.IGNORECASE)

        for filename, fid in links.items():
            if pattern.search(filename):
                return fid
        return None

    # ---------------------------------------------------------
    # IMPLEMENTAÇÃO INTERNA / ADAPTADORES PRIVADOS
    # ---------------------------------------------------------

    def _load_from_local(self, pc_num: str) -> Optional[PdfDocument]:
        """Adaptador Local: busca arquivos .pdf no disco."""
        pc_clean = pc_num.lstrip("0")
        candidate_dirs = [
            os.path.join(self.base_dir, "pedidos_pdf"),
            os.path.join(os.path.dirname(self.base_dir), "pedidos_pdf"),
            os.path.join(self.base_dir, "data", "pdfs")
        ]

        for folder in candidate_dirs:
            if not os.path.exists(folder):
                continue
            candidates = (
                glob.glob(os.path.join(folder, f"PedidoCompra*{pc_clean}*.pdf")) +
                glob.glob(os.path.join(folder, f"PC_*{pc_clean}*.pdf"))
            )
            for c_path in candidates:
                base = os.path.basename(c_path)
                # Validação estrita para não pegar PC 1123 quando buscar 123
                if re.search(rf"^PedidoCompra0*{pc_clean}[_.]|^PC_?0*{pc_clean}[_.]", base, re.IGNORECASE):
                    try:
                        with open(c_path, "rb") as f:
                            data = f.read()
                        return PdfDocument(
                            content=data,
                            filename=f"PC_{pc_num}.pdf",
                            source="local"
                        )
                    except OSError:
                        pass
        return None

    def _load_from_telegram(self, pc_num: str) -> Optional[PdfDocument]:
        """Adaptador Cloud: busca arquivo via Telegram Bot API."""
        fid = self.find_file_id(pc_num)
        if not fid:
            return None

        try:
            info_url = f"https://api.telegram.org/bot{self.telegram_token}/getFile?file_id={fid}"
            r_info = requests.get(info_url, timeout=self.timeout).json()
            if not r_info.get("ok"):
                logger.warning(f"[PdfStorage] Falha no getFile do Telegram para PC {pc_num}: {r_info}")
                return None

            file_path = r_info["result"]["file_path"]
            dl_url = f"https://api.telegram.org/file/bot{self.telegram_token}/{file_path}"
            pdf_bytes = requests.get(dl_url, timeout=self.timeout).content

            if pdf_bytes and pdf_bytes.startswith(b"%PDF"):
                return PdfDocument(
                    content=pdf_bytes,
                    filename=f"PC_{pc_num}.pdf",
                    source="telegram"
                )
        except Exception as e:
            logger.error(f"[PdfStorage] Erro ao baixar PDF {pc_num} do Telegram: {e}")

        return None

    def _get_links_map(self) -> Dict[str, str]:
        """Carrega e mantém em memória cache os links do pdf_links.json."""
        possible_paths = [
            os.path.join(self.base_dir, "data", "pdf_links.json"),
            os.path.join(os.path.dirname(self.base_dir), "data", "pdf_links.json"),
            "data/pdf_links.json"
        ]

        found_path = next((p for p in possible_paths if os.path.exists(p)), None)
        if not found_path:
            return {}

        try:
            mtime = os.path.getmtime(found_path)
            if self._links_cache is None or mtime > self._links_mtime:
                with open(found_path, "r", encoding="utf-8") as f:
                    self._links_cache = json.load(f)
                self._links_mtime = mtime
            return self._links_cache or {}
        except Exception as e:
            logger.warning(f"[PdfStorage] Erro ao ler pdf_links.json: {e}")
            return self._links_cache or {}
