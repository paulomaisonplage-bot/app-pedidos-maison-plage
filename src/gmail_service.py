"""
Módulo de Integração com o Gmail via IMAP (Direto e Otimizado para Sienge).

Conecta ao Gmail de forma segura via SSL, localiza e-mails de Pedidos de Compra
enviados por Josivan Pajau / Sienge e baixa os relatórios em PDF automaticamente.
"""

import os
import sys
import json
import imaplib
import email
from email.header import decode_header
from typing import List, Dict, Any, Optional

# Garante saída UTF-8 no Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def decode_mime_words(s: Optional[str]) -> str:
    if not s:
        return ""
    decoded_fragments = decode_header(s)
    result = []
    for fragment, encoding in decoded_fragments:
        if isinstance(fragment, bytes):
            if encoding:
                try:
                    result.append(fragment.decode(encoding, errors="replace"))
                except Exception:
                    result.append(fragment.decode("utf-8", errors="replace"))
            else:
                result.append(fragment.decode("utf-8", errors="replace"))
        else:
            result.append(str(fragment))
    return "".join(result)


class GmailPurchaseOrderFetcher:
    """
    Cliente Gmail para busca e download rápido de Pedidos de Compra do Sienge.
    """

    def __init__(
        self,
        config_file: str = "data/gmail_config.json",
        history_file: str = "data/gmail_historico.json",
        output_dir: str = "pedidos_pdf"
    ):
        self.config_file = os.path.abspath(config_file)
        self.history_file = os.path.abspath(history_file)
        self.output_dir = os.path.abspath(output_dir)

        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)

    def _load_config(self) -> Dict[str, str]:
        config = {"email": "", "app_password": ""}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config.update(json.load(f))
            except Exception:
                pass
        return config

    def save_config(self, email_address: str, app_password: str):
        clean_pwd = app_password.replace(" ", "").strip()
        config = {
            "email": email_address.strip(),
            "app_password": clean_pwd
        }
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def _load_history(self) -> Dict[str, Any]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {"processed_message_ids": [], "downloaded_files": []}

    def _save_history(self, history: Dict[str, Any]):
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

    def fetch_and_download_attachments(
        self,
        query: str = "Pedido de Compra",
        sender_filter: str = "Josivan",
        force_recheck: bool = False
    ) -> List[str]:
        config = self._load_config()
        user_email = config.get("email", "").strip()
        app_password = config.get("app_password", "").strip()

        if not user_email or not app_password:
            print("\n" + "=" * 75)
            print("[!] CONFIGURAÇÃO DO GMAIL NECESSÁRIA")
            print("=" * 75)
            print("Informe seu endereço do Gmail e a Senha de Aplicativo de 16 letras.")
            print("=" * 75 + "\n")
            return []

        history = self._load_history()
        processed_ids = set(history.get("processed_message_ids", []))
        downloaded_paths = []

        print(f"\n[+] Conectando ao Gmail ({user_email}) via conexão segura SSL...")

        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com", port=993)
            mail.login(user_email, app_password)
            print("[OK] Autenticado com sucesso no Gmail!")

            mail.select("INBOX")

            # Busca e-mails de Josivan ou com assunto Pedido de Compra
            search_query = '(OR (FROM "Josivan") (FROM "sienge.com.br"))'
            print(f"[+] Buscando e-mails de Josivan Pajau / Sienge na Caixa de Entrada...")

            status, data = mail.search(None, search_query)
            if status != "OK" or not data or not data[0]:
                # Tenta por assunto se a busca por remetente vier vazia
                status, data = mail.search(None, '(SUBJECT "Pedido de Compra")')

            if status != "OK" or not data or not data[0]:
                print("[-] Nenhum e-mail correspondente localizado.")
                mail.logout()
                return []

            msg_ids = data[0].split()
            print(f"[+] Localizados {len(msg_ids)} e-mail(s). Verificando novos anexos em PDF...")

            # Percorre dos mais novos para os mais antigos
            for msg_id_bytes in reversed(msg_ids):
                msg_id_str = msg_id_bytes.decode()

                # Primeiro checa cabeçalhos rapidamente
                status, hdr_data = mail.fetch(msg_id_bytes, '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID)])')
                if status != "OK" or not hdr_data or not hdr_data[0]:
                    continue

                hdr_text = hdr_data[0][1]
                msg_hdr = email.message_from_bytes(hdr_text)
                subject = decode_mime_words(msg_hdr.get("Subject", ""))
                from_header = decode_mime_words(msg_hdr.get("From", ""))
                msg_uid = msg_hdr.get("Message-ID", msg_id_str).strip()

                # Se já foi processado anteriormente, pula
                if not force_recheck and msg_uid in processed_ids:
                    continue

                # Baixa corpo completo da mensagem
                status, full_data = mail.fetch(msg_id_bytes, '(RFC822)')
                if status != "OK" or not full_data or not full_data[0]:
                    continue

                raw_msg = email.message_from_bytes(full_data[0][1])

                # Se for cancelamento, adiciona um marcador no nome do arquivo (ajuda processar_pedidos.py)
                is_cancelled = bool(re.search(r'cancelad[oa]|cancelamento', subject, re.IGNORECASE))

                has_pdf = False
                for part in raw_msg.walk():
                    if part.get_content_maintype() == 'multipart' or part.get('Content-Disposition') is None:
                        continue

                    filename = part.get_filename()
                    if filename and (filename.lower().endswith('.pdf') or filename.lower().endswith('.txt')):
                        filename = decode_mime_words(filename)
                        if is_cancelled and "[CANCELADO]" not in filename.upper():
                            filename = f"[CANCELADO]_{filename}"

                        file_data = part.get_payload(decode=True)
                        if not file_data:
                            continue

                        clean_filename = "".join(c if c.isalnum() or c in " ._-[]" else "_" for c in filename)
                        file_path = os.path.join(self.output_dir, clean_filename)

                        try:
                            with open(file_path, "wb") as f:
                                f.write(file_data)
                            downloaded_paths.append(file_path)
                            print(f"   [✓] Baixado: {clean_filename}")
                            has_pdf = True

                            # Camada 1: Upload Atômico Imediato para o Telegram
                            try:
                                from src.pdf_telegram_service import upload_pdf_to_telegram, _load_cache, _save_cache
                                bot_token = os.environ.get("TELEGRAM_TOKEN", "8847996417:AAGItLPuNaHN0girA46486IaESdPZ8w7bzA")
                                cache = _load_cache()
                                if clean_filename not in cache:
                                    fid = upload_pdf_to_telegram(bot_token, file_path)
                                    if fid:
                                        cache[clean_filename] = fid
                                        _save_cache(cache)
                                        print(f"   [✓] Telegram file_id gerado na origem: {fid[:16]}...")
                            except Exception as e_up:
                                print(f"   [!] Aviso no upload atômico ao Telegram: {e_up}")

                        except Exception as e:
                            print(f"   [X] Erro ao salvar {clean_filename}: {e}")

                if has_pdf or not force_recheck:
                    processed_ids.add(msg_uid)
                    self._save_history({"processed_message_ids": list(processed_ids)})
            
            history["processed_message_ids"] = list(processed_ids)
            history["downloaded_files"].extend([os.path.basename(p) for p in downloaded_paths])
            self._save_history(history)

            mail.logout()

            print(f"\n[OK] Download finalizado! Total de {len(downloaded_paths)} novo(s) PDF(s) baixado(s) do Gmail.")
            return downloaded_paths

        except Exception as e:
            print(f"\n[X] Erro ao conectar ou baixar do Gmail: {e}")
            return []

    def fetch_specific_order_pdf(self, pc_number: str) -> Optional[str]:
        """
        Camada 3 (Self-Healing Sob Demanda):
        Busca especificamente o PDF de um determinado número de PC no Gmail,
        salva em disco, faz upload no Telegram e retorna o caminho do arquivo.
        """
        config = self._load_config()
        user_email = config.get("email", "").strip()
        app_password = config.get("app_password", "").strip()

        if not user_email or not app_password:
            return None

        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com", port=993)
            mail.login(user_email, app_password)
            mail.select("INBOX")

            status, data = mail.search(None, f'(SUBJECT "{pc_number}")')
            if status != "OK" or not data or not data[0]:
                status, data = mail.search(None, '(SUBJECT "Pedido de Compra")')

            if status != "OK" or not data or not data[0]:
                mail.logout()
                return None

            msg_ids = data[0].split()
            for mid in reversed(msg_ids):
                status, full_data = mail.fetch(mid, '(RFC822)')
                if status != "OK" or not full_data or not full_data[0]:
                    continue
                raw_msg = email.message_from_bytes(full_data[0][1])
                for part in raw_msg.walk():
                    if part.get_content_maintype() == 'multipart' or part.get('Content-Disposition') is None:
                        continue
                    filename = part.get_filename()
                    if filename and filename.lower().endswith('.pdf'):
                        filename = decode_mime_words(filename)
                        clean_fn = "".join(c if c.isalnum() or c in " ._-[]" else "_" for c in filename)
                        
                        # Verifica se o arquivo é compatível com o PC
                        if f"pedidocompra{pc_number}_" in clean_fn.lower() or f"pc_{pc_number}" in clean_fn.lower() or f"_{pc_number}." in clean_fn.lower() or f"_{pc_number}_" in clean_fn.lower():
                            file_data = part.get_payload(decode=True)
                            if not file_data:
                                continue
                            os.makedirs(self.output_dir, exist_ok=True)
                            file_path = os.path.join(self.output_dir, clean_fn)
                            with open(file_path, "wb") as f:
                                f.write(file_data)
                            
                            # Upload imediato para gerar file_id
                            try:
                                from src.pdf_telegram_service import upload_pdf_to_telegram, _load_cache, _save_cache
                                bot_token = os.environ.get("TELEGRAM_TOKEN", "8847996417:AAGItLPuNaHN0girA46486IaESdPZ8w7bzA")
                                cache = _load_cache()
                                fid = upload_pdf_to_telegram(bot_token, file_path)
                                if fid:
                                    cache[clean_fn] = fid
                                    _save_cache(cache)
                            except Exception:
                                pass

                            mail.logout()
                            return file_path

            mail.logout()
            return None
        except Exception:
            return None

