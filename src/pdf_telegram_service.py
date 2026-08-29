import os
import json
import logging
import requests
from typing import Optional, Dict

logger = logging.getLogger(__name__)

CACHE_PATH = os.path.abspath("data/pdf_links.json")
# Chat de armazenamento: chat do Paulo com o bot (notificacao silenciosa)
STORAGE_CHAT_ID = "8459937324"

def _load_cache() -> Dict[str, str]:
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_cache(cache: Dict[str, str]):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

def _commit_cache_to_github():
    try:
        from dulwich import porcelain
        token = os.environ.get("GITHUB_TOKEN", "")
        repo_url = f"https://paulomaisonplage-bot:{token}@github.com/paulomaisonplage-bot/bot-pedidos-maison-plage.git"
        repo = porcelain.open_repo(".")
        porcelain.add(repo, paths=["data/pdf_links.json"])
        porcelain.commit(
            repo,
            message=b"chore: atualiza cache de file_ids dos PDFs no Telegram",
            author=b"RoboMaison <robo@maisonplage.com.br>"
        )
        porcelain.push(repo, repo_url,
            refspecs=[b"refs/heads/master:refs/heads/main",
                      b"refs/heads/master:refs/heads/master"],
            force=True
        )
        logger.info("[PDF Telegram] Cache persistido no GitHub.")
    except Exception as e:
        logger.warning(f"[PDF Telegram] Falha ao persistir cache no GitHub: {e}")

def get_file_id(filename: str) -> Optional[str]:
    if not filename:
        return None
    cache = _load_cache()
    return cache.get(os.path.basename(filename))

def upload_pdf_to_telegram(bot_token: str, pdf_path: str) -> Optional[str]:
    if not os.path.exists(pdf_path):
        return None
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    try:
        with open(pdf_path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": STORAGE_CHAT_ID, "disable_notification": "true"},
                files={"document": (os.path.basename(pdf_path), f, "application/pdf")},
                timeout=60
            )
        if resp.ok:
            result = resp.json().get("result", {})
            doc = result.get("document", {})
            file_id = doc.get("file_id")
            if file_id:
                return file_id
            logger.warning(f"[PDF Telegram] Resposta sem file_id: {resp.text[:200]}")
        else:
            logger.warning(f"[PDF Telegram] Erro ao enviar {os.path.basename(pdf_path)}: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"[PDF Telegram] Excecao ao enviar {pdf_path}: {e}")
    return None

def sync_pdfs_to_telegram(bot_token: str, pdf_dir: str = "pedidos_pdf") -> int:
    pdf_dir_abs = os.path.abspath(pdf_dir)
    if not os.path.exists(pdf_dir_abs):
        logger.info(f"[PDF Telegram] Pasta {pdf_dir_abs} nao encontrada.")
        return 0

    cache = _load_cache()
    uploaded = 0
    batch_size = 10

    pdf_files = [f for f in os.listdir(pdf_dir_abs)
                 if f.lower().endswith(".pdf") and f"PedidoCompra" in f]

    for filename in pdf_files:
        if filename in cache:
            continue
        pdf_path = os.path.join(pdf_dir_abs, filename)
        file_id = upload_pdf_to_telegram(bot_token, pdf_path)
        if file_id:
            cache[filename] = file_id
            uploaded += 1
            logger.info(f"[PDF Telegram] Enviado: {filename}")
            if uploaded % batch_size == 0:
                _save_cache(cache)
                _commit_cache_to_github()

    if uploaded > 0:
        _save_cache(cache)
        _commit_cache_to_github()

    logger.info(f"[PDF Telegram] Ciclo concluido: {uploaded} novo(s) enviado(s).")
    return uploaded
