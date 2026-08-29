"""
Módulo de Sincronização com o Google Drive
Permite baixar e sincronizar a planilha oficial de pedidos de compra direto do Google Drive.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

class DriveSyncService:
    def __init__(self, drive_file_id: str = None, destination_path: str = "data/pedidos_compra_consolidado.xlsx"):
        self.drive_file_id = drive_file_id or os.getenv("GOOGLE_DRIVE_EXCEL_ID")
        self.destination_path = destination_path

    def sync_from_drive(self) -> bool:
        """Baixa a versão mais recente da planilha do Google Drive."""
        if not self.drive_file_id:
            logger.info("[DRIVE] GOOGLE_DRIVE_EXCEL_ID não configurado. Usando base de dados local.")
            return False

        try:
            url = f"https://drive.google.com/uc?export=download&id={self.drive_file_id}"
            logger.info(f"[DRIVE] Baixando planilha oficial do Google Drive ID: {self.drive_file_id}...")
            r = requests.get(url, timeout=30)
            if r.status_code == 200 and len(r.content) > 1000:
                os.makedirs(os.path.dirname(self.destination_path), exist_ok=True)
                with open(self.destination_path, "wb") as f:
                    f.write(r.content)
                logger.info(f"[DRIVE] Planilha atualizada com sucesso ({len(r.content):,} bytes).")
                return True
            else:
                logger.warning(f"[DRIVE] Resposta inesperada ao baixar do Drive: Status {r.status_code}")
                return False
        except Exception as e:
            logger.error(f"[DRIVE] Erro ao sincronizar com Google Drive: {e}")
            return False
