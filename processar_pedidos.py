"""
Script Principal para Processamento de Pedidos de Compra (Sienge).

Varre a pasta 'pedidos_pdf/', extrai todos os dados dos relatórios em PDF/TXT do Sienge
e consolida na planilha Excel 'data/pedidos_compra_consolidado.xlsx'.

Uso:
    python processar_pedidos.py
"""

import os
import sys
import glob
from pathlib import Path

# Garante compatibilidade de saída UTF-8 no Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from typing import Optional, List
from src.pdf_extractor import SiengePDFExtractor
from src.excel_manager import ExcelManager, ExcelDatabaseManager


def process_all_orders(
    pdf_dir: str = "pedidos_pdf",
    excel_path: str = "data/pedidos_compra_consolidado.xlsx",
    files_to_process: Optional[List[str]] = None
):
    print("=" * 70)
    print("  SISTEMA DE GERENCIAMENTO DE PEDIDOS DE COMPRA (SIENGE)")
    print("=" * 70)

    pdf_folder = os.path.abspath(pdf_dir)
    os.makedirs(pdf_folder, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(excel_path)), exist_ok=True)

    # Modo incremental: se uma lista de arquivos específicos foi fornecida
    if files_to_process is not None:
        if not files_to_process:
            print("[i] Nenhum novo arquivo para processar. Base mantida inalterada.")
            return
        pdf_files = sorted([os.path.abspath(f) for f in files_to_process if os.path.exists(f)])
    else:
        # Busca todos os arquivos PDF e TXT da pasta
        pdf_files = sorted(glob.glob(os.path.join(pdf_folder, "*.pdf")) + glob.glob(os.path.join(pdf_folder, "*.txt")))

    if not pdf_files:
        print(f"\n[!] Nenhum arquivo de pedido encontrado para processamento.")
        return

    print(f"\n[+] Processando {len(pdf_files)} arquivo(s)...")

    extractor = SiengePDFExtractor()
    manager = ExcelDatabaseManager(excel_path)

    extracted_orders = []
    total_items_found = 0


    for file_path in pdf_files:
        filename = os.path.basename(file_path)
        print(f"\n-> Processando: {filename}...")
        
        try:
            if "[CANCELADO]" in filename.upper():
                order_data = extractor.extract_from_pdf(file_path)
                num_pedido = order_data.get("numero_pedido")
                if num_pedido:
                    manager.remove_orders([num_pedido])
                    print(f"   [!] Pedido No: {num_pedido} CANCELADO com sucesso da base.")
                else:
                    print(f"   [X] Nao foi possivel extrair o numero do pedido cancelado: {filename}")
                continue

            order_data = extractor.extract_from_pdf(file_path)
            num_pedido = order_data.get("numero_pedido") or "Desconhecido"
            data_ped = order_data.get("data_pedido") or "N/D"
            fornec = order_data.get("fornecedor", {}).get("nome") or "N/D"
            itens = order_data.get("itens", [])
            data_entrega = order_data.get("condicoes", {}).get("data_entrega") or "N/D"
            total_ped_str = order_data.get("total_pedido_str") or "0,00"

            print(f"   [OK] Pedido No: {num_pedido} | Emissao: {data_ped}")
            print(f"   [OK] Fornecedor: {fornec}")
            print(f"   [OK] Entrega Prevista: {data_entrega} | Total: R$ {total_ped_str}")
            print(f"   [OK] Itens extraidos: {len(itens)}")

            for item in itens:
                cod = item.get("codigo")
                desc = item.get("descricao")
                qtde = item.get("quantidade_str")
                unid = item.get("unidade")
                pr_unit = item.get("preco_unitario_str")
                tot_item = item.get("preco_final_str")
                print(f"        * [{cod}] {desc[:40]}... -> {qtde} {unid} x R$ {pr_unit} = R$ {tot_item}")

            extracted_orders.append(order_data)
            total_items_found += len(itens)

        except Exception as e:
            print(f"   [X] Erro ao extrair {filename}: {e}")

    # Sincroniza com a planilha Excel
    print("\n" + "-" * 70)
    print("Sincronizando com a base de dados Excel...")
    total_registros = manager.sync_extracted_orders(extracted_orders)

    print(f"[OK] Sucesso! Total de {total_registros} itens consolidados na planilha:")
    print(f"     -> {os.path.abspath(excel_path)}")
    print("=" * 70)



if __name__ == "__main__":
    process_all_orders()
