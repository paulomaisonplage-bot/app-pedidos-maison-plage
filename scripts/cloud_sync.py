import os
import sys
import shutil
import json
import glob
import time
import requests

# Garante saída imediata sem buffer
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.gmail_service import GmailPurchaseOrderFetcher
from processar_pedidos import process_all_orders


def upload_missing_pdfs_to_telegram():
    token = "8847996417:AAGItLPuNaHN0girA46486IaESdPZ8w7bzA"
    chat_id = "8459937324"
    cache_path = os.path.join(BASE_DIR, "data", "pdf_links.json")
    
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}
            
    pdf_files = glob.glob(os.path.join(BASE_DIR, "pedidos_pdf", "PedidoCompra*.pdf"))
    missing = [pf for pf in pdf_files if os.path.basename(pf) not in cache]
    
    if not missing:
        print("[OK] Todos os PDFs já estão indexados no Telegram.", flush=True)
        return
        
    print(f"[+] Enviando {len(missing)} novos PDFs para o Telegram Bot...", flush=True)
    success = 0
    for pf in missing:
        fn = os.path.basename(pf)
        url = f"https://api.telegram.org/bot{token}/sendDocument"
        try:
            with open(pf, "rb") as f:
                resp = requests.post(
                    url,
                    data={"chat_id": chat_id, "caption": f"Pedido {fn}"},
                    files={"document": (fn, f, "application/pdf")},
                    timeout=30
                )
            data = resp.json()
            if data.get("ok"):
                fid = data.get("result", {}).get("document", {}).get("file_id")
                if fid:
                    cache[fn] = fid
                    success += 1
        except Exception as e:
            print(f"[-] Erro ao enviar {fn} para o Telegram: {e}", flush=True)
        time.sleep(0.3)
        
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
        
    dst_cache = os.path.join(BASE_DIR, "webapp_maison_plage", "data", "pdf_links.json")
    if os.path.exists(os.path.dirname(dst_cache)):
        shutil.copy(cache_path, dst_cache)
        
    print(f"[OK] {success} novos PDFs indexados com sucesso no Telegram!", flush=True)


def generate_json_cache():
    from src.excel_manager import ExcelManager
    src_excel = os.path.join(BASE_DIR, "data", "pedidos_compra_consolidado.xlsx")
    if not os.path.exists(src_excel):
        return
        
    mgr = ExcelManager(src_excel)
    records = mgr.load_existing_records()
    by_pc = {}
    for r in records.values():
        pc = str(r.get("numero_pedido", "")).strip()
        if pc:
            if pc not in by_pc:
                by_pc[pc] = []
            by_pc[pc].append(r)
            
    payload = {
        "mtime": os.path.getmtime(src_excel) if os.path.exists(src_excel) else time.time(),
        "total_orders": len(by_pc),
        "total_items": len(records),
        "orders_by_pc": by_pc
    }
    
    for c_path in [
        os.path.join(BASE_DIR, "data", "pedidos_cache.json"),
        os.path.join(BASE_DIR, "webapp_maison_plage", "data", "pedidos_cache.json")
    ]:
        if os.path.exists(os.path.dirname(c_path)):
            with open(c_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
    print(f"[OK] Cache ultra-rápido gerado com {len(by_pc)} pedidos e {len(records)} itens!", flush=True)


def main():
    fetcher = GmailPurchaseOrderFetcher()
    
    # Se estiver rodando no GitHub Actions com secrets em variáveis de ambiente:
    user_email = os.getenv("GMAIL_USER", "").strip()
    app_pwd = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if user_email and app_pwd:
        fetcher.save_config(user_email, app_pwd)

    print("[+] Buscando novos pedidos de compra no Gmail...", flush=True)
    # Busca pedidos com assunto "Pedido de Compra" do Sienge
    files = fetcher.fetch_and_download_attachments(
        query="Pedido de Compra",
        sender_filter="sienge"
    )
    
    if files:
        print(f"[+] {len(files)} novos PDFs baixados. Consolidando base Excel...", flush=True)
        process_all_orders()
        
        # Garante cópia para a pasta do webapp onde o Vercel executa
        src_excel = os.path.join(BASE_DIR, "data", "pedidos_compra_consolidado.xlsx")
        dst_excel = os.path.join(BASE_DIR, "webapp_maison_plage", "data", "pedidos_compra_consolidado.xlsx")
        if os.path.exists(src_excel):
            os.makedirs(os.path.dirname(dst_excel), exist_ok=True)
            shutil.copy(src_excel, dst_excel)
            print(f"[OK] Cópia para {dst_excel} realizada com sucesso!", flush=True)
            
        # Indexa no telegram e gera cache json
        upload_missing_pdfs_to_telegram()
        generate_json_cache()
        print("[OK] Base de dados, PDFs e Cache atualizados com sucesso!", flush=True)
    else:
        print("[OK] Base já está 100% atualizada. Nenhum novo pedido pendente.", flush=True)


if __name__ == "__main__":
    main()
