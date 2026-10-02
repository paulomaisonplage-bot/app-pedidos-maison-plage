import os
import sys

# Garante saída imediata sem buffer
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.gmail_service import GmailPurchaseOrderFetcher
from processar_pedidos import process_all_orders


def main():
    fetcher = GmailPurchaseOrderFetcher()
    
    # Se estiver rodando no GitHub Actions com secrets em variáveis de ambiente:
    user_email = os.getenv("GMAIL_USER", "").strip()
    app_pwd = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if user_email and app_pwd:
        fetcher.save_config(user_email, app_pwd)

    print("[+] Buscando novos pedidos de compra no Gmail...", flush=True)
    files = fetcher.fetch_and_download_attachments(
        query="Pedido de Compra",
        sender_filter="Josivan"
    )
    
    if files:
        print(f"[+] {len(files)} novos PDFs baixados. Consolidando base Excel...", flush=True)
        process_all_orders()
        print("[OK] Base de dados Excel atualizada com sucesso!", flush=True)
    else:
        print("[OK] Base já está 100% atualizada. Nenhum novo pedido pendente.", flush=True)


if __name__ == "__main__":
    main()
