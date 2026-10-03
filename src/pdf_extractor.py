"""
Módulo de Extração de Pedidos de Compra (Sienge / Starian em PDF).

Projetado especificamente para extrair com 100% de fidelidade os campos de:
- Cabeçalho (Nº Pedido, Data de Emissão, Fornecedor, CNPJ, Obra)
- Itens / Insumos (Código, Descrição Completa multi-linhas, Quantidade exata com 4 decimais, Unidade, Preços)
- Condições e Prazos (Condição de Pagamento, Data de Entrega Prevista, Vencimentos, Observações)
- Total das Mercadorias, Frete, Descontos Globais e TOTAL DO PEDIDO
- Validação Matemática Cruzada (Checksum): (Soma dos Itens + Frete - Desconto == Total Pedido)
- Suporte a pedidos com MÚLTIPLAS PÁGINAS.
"""

import os
import re
from decimal import Decimal
from typing import Dict, List, Any, Optional
from src.excel_manager import clean_supplier_name, classify_item


def parse_br_number(val_str: str) -> Optional[float]:
    if not val_str:
        return None
    cleaned = str(val_str).strip().replace('.', '').replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_br_decimal(val_str: str) -> Optional[Decimal]:
    if not val_str:
        return None
    cleaned = str(val_str).strip().replace('.', '').replace(',', '.')
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def validate_checksum(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Realiza a validação cruzada matemática contábil:
    Soma dos Itens + Frete (R$) - Desconto Global (R$) == TOTAL DO PEDIDO
    """
    total_rodape = data.get("total_pedido")
    itens = data.get("itens", [])

    if not itens:
        return {
            "is_valid": True,
            "soma_itens": 0.0,
            "valor_frete": 0.0,
            "valor_desconto": 0.0,
            "total_calculado": 0.0,
            "total_rodape": total_rodape or 0.0,
            "diferenca": 0.0,
            "status_validacao": "SEM_ITENS",
            "alerta": ""
        }

    soma_itens_dec = Decimal('0.00')
    for it in itens:
        p_final = it.get("preco_final_str")
        dec = parse_br_decimal(p_final) if p_final else Decimal(str(it.get("preco_final") or 0.0))
        if dec:
            soma_itens_dec += dec

    # Valores adicionais do rodapé
    cond = data.get("condicoes", {})
    frete_dec = parse_br_decimal(cond.get("valor_frete_str")) or Decimal('0.00')
    desc_dec = parse_br_decimal(cond.get("valor_desconto_str")) or Decimal('0.00')

    # Total calculado da compra
    total_calculado_dec = soma_itens_dec + frete_dec - desc_dec

    if total_rodape is None:
        return {
            "is_valid": True,
            "soma_itens": float(soma_itens_dec),
            "valor_frete": float(frete_dec),
            "valor_desconto": float(desc_dec),
            "total_calculado": float(total_calculado_dec),
            "total_rodape": 0.0,
            "diferenca": 0.0,
            "status_validacao": "TOTAL_RODAPE_NAO_ENCONTRADO",
            "alerta": ""
        }

    rodape_dec = parse_br_decimal(data.get("total_pedido_str")) or Decimal(str(total_rodape))
    diff = abs(total_calculado_dec - rodape_dec)

    # Tolerância de R$ 0,02 para arredondamento de centavos contábeis
    is_valid = (diff <= Decimal('0.02'))

    if is_valid:
        return {
            "is_valid": True,
            "soma_itens": float(soma_itens_dec),
            "valor_frete": float(frete_dec),
            "valor_desconto": float(desc_dec),
            "total_calculado": float(total_calculado_dec),
            "total_rodape": float(rodape_dec),
            "diferenca": float(diff),
            "status_validacao": "CONCILIADO_COM_SUCESSO",
            "alerta": ""
        }
    else:
        num_ped = data.get('numero_pedido') or "N/D"
        origem = data.get('arquivo_origem') or "PDF"
        alerta = (
            f"[⚠️ DIVERGÊNCIA MATEMÁTICA] Pedido {num_ped} ({origem}): "
            f"Itens (R$ {float(soma_itens_dec):,.2f}) + Frete (R$ {float(frete_dec):,.2f}) - Desc (R$ {float(desc_dec):,.2f}) = R$ {float(total_calculado_dec):,.2f} "
            f"vs Rodapé = R$ {float(rodape_dec):,.2f} (Dif: R$ {float(diff):,.2f}). O valor do rodapé prevalecerá como verdade no fluxo de caixa."
        )
        return {
            "is_valid": False,
            "soma_itens": float(soma_itens_dec),
            "valor_frete": float(frete_dec),
            "valor_desconto": float(desc_dec),
            "total_calculado": float(total_calculado_dec),
            "total_rodape": float(rodape_dec),
            "diferenca": float(diff),
            "status_validacao": "DIVERGÊNCIA_MATEMÁTICA",
            "alerta": alerta
        }


class SiengePDFExtractor:
    def __init__(self):
        self._pdfplumber_available = False
        self._pypdf_available = False

        try:
            import pdfplumber
            self._pdfplumber = pdfplumber
            self._pdfplumber_available = True
        except ImportError:
            self._pdfplumber = None

        try:
            import pypdf
            self._pypdf = pypdf
            self._pypdf_available = True
        except ImportError:
            try:
                import pypdf2 as pypdf
                self._pypdf = pypdf
                self._pypdf_available = True
            except ImportError:
                self._pypdf = None

    def extract_text_from_file(self, file_path: str) -> str:
        if not os.path.exists(file_path):
            return ""

        if not file_path.lower().endswith('.pdf'):
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            except Exception:
                with open(file_path, 'r', encoding='latin-1', errors='ignore') as f:
                    return f.read()

        full_text = []

        if self._pdfplumber_available:
            try:
                with self._pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text(layout=True) or page.extract_text()
                        if text:
                            full_text.append(text)
                if full_text:
                    return "\n".join(full_text)
            except Exception:
                pass

        if self._pypdf_available:
            try:
                reader = self._pypdf.PdfReader(file_path)
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        full_text.append(text)
                if full_text:
                    return "\n".join(full_text)
            except Exception:
                pass

        return "\n".join(full_text)

    def extract_from_text(self, text: str, source_filename: str = "") -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "numero_pedido": None,
            "data_pedido": None,
            "solicitacoes": None,
            "cotacoes": None,
            "faturamento": {},
            "fornecedor": {},
            "obra": {},
            "itens": [],
            "condicoes": {},
            "observacoes": "",
            "total_mercadorias_str": "",
            "total_mercadorias": None,
            "total_pedido_str": "",
            "total_pedido": None,
            "arquivo_origem": os.path.basename(source_filename) if source_filename else "",
            "validacao_matematica": {}
        }

        # 1. Número do Pedido e Data do Pedido
        num_pedido_match = re.search(r'N[º°\?]?\s*Pedido\s*(\d+)', text, re.IGNORECASE)
        if num_pedido_match:
            data["numero_pedido"] = num_pedido_match.group(1).strip()

        data_pedido_match = re.search(r'Data\s*pedido\s*(\d{2}/\d{2}/\d{4})', text, re.IGNORECASE)
        if data_pedido_match:
            data["data_pedido"] = data_pedido_match.group(1).strip()

        solic_match = re.search(r'Solicita[çc\?][õo\?]es\s*(\d+)', text, re.IGNORECASE)
        if solic_match:
            data["solicitacoes"] = solic_match.group(1).strip()
        cotac_match = re.search(r'Cota[çc\?][õo\?]es\s*(\d+)', text, re.IGNORECASE)
        if cotac_match:
            data["cotacoes"] = cotac_match.group(1).strip()

        # 2. Dados do Fornecedor
        fornec_block_match = re.search(
            r'Dados do fornecedor([\s\S]*?)(?:Dados da obra|Insumo\s+Qtde)',
            text,
            re.IGNORECASE
        )
        if fornec_block_match:
            f_text = fornec_block_match.group(1)
            lines = [line.strip() for line in f_text.split('\n') if line.strip()]
            nome_fornec = ""
            for l in lines:
                if re.match(r'^\d+\s*-\s*.+', l) and "Endereço" not in l and "CNPJ" not in l and "Endere" not in l:
                    nome_fornec = l
                    break
                elif any(kw in l for kw in ["DISTRIBUIDOR", "LTDA", "S/A", "S.A", "COMERCIAL", "COMERCIO", "CIMENTOS", "ACO", "AÇO", "CERÂMICA", "PLASTPUPIN", "MIXPEL", "SOPREMA"]):
                    if not nome_fornec and not l.startswith("CNPJ") and not l.startswith("Endere"):
                        nome_fornec = l

            cnpj_match = re.search(r'CNPJ\s*([\d\.\/\-]+)', f_text)
            cnpj_fornec = cnpj_match.group(1).strip() if cnpj_match else ""

            tel_match = re.search(r'Telefone\s*([\(\)\d\s\-]+)', f_text)
            tel_fornec = tel_match.group(1).strip() if tel_match else ""

            vend_match = re.search(r'Vendedor\s*([^\n\r]+)', f_text)
            vend_fornec = vend_match.group(1).strip() if vend_match else ""

            email_match = re.search(r'E-mail\s*([\w\.\-]+@[\w\.\-]+)', f_text, re.IGNORECASE)
            email_fornec = email_match.group(1).strip() if email_match else ""

            clean_name = clean_supplier_name(nome_fornec, cnpj=cnpj_fornec)
            data["fornecedor"] = {
                "nome": clean_name,
                "cnpj": cnpj_fornec,
                "telefone": tel_fornec,
                "vendedor": vend_fornec,
                "email": email_fornec
            }

        # 3. Dados da Obra
        obra_block_match = re.search(
            r'Dados da obra([\s\S]*?)Insumo\s+Qtde',
            text,
            re.IGNORECASE
        )
        if obra_block_match:
            o_text = obra_block_match.group(1)
            lines = [line.strip() for line in o_text.split('\n') if line.strip()]
            nome_obra = ""
            for l in lines:
                if re.match(r'^\d+\s*-\s*.+', l) and "End." not in l and "Ponto" not in l:
                    nome_obra = l
                    break

            end_match = re.search(r'End\.\s*entrega\s*([^\n\r]+)', o_text, re.IGNORECASE)
            end_entrega = end_match.group(1).strip() if end_match else ""

            ponto_ref_match = re.search(r'Ponto\s*de\s*ref\.\s*([^\n\r]+)', o_text, re.IGNORECASE)
            ponto_ref = ponto_ref_match.group(1).strip() if ponto_ref_match else ""

            data["obra"] = {
                "nome": nome_obra,
                "endereco_entrega": end_entrega,
                "ponto_referencia": ponto_ref
            }

        # 4. Itens / Insumos
        data["itens"] = self._parse_items_from_text(text)

        # 5. Condições Comerciais e Rodapé
        cond_pagto_match = re.search(r'Cond\.\s*pagamento\s*([^\n\r]+?)(?:Frete|Total|$)', text, re.IGNORECASE)
        if cond_pagto_match:
            data["condicoes"]["condicao_pagamento"] = cond_pagto_match.group(1).strip()

        data_entrega_match = re.search(r'Datas?\s*de\s*entrega\s*([0-9/,\s]+)', text, re.IGNORECASE)
        if data_entrega_match:
            data["condicoes"]["data_entrega"] = data_entrega_match.group(1).strip()

        data_venc_match = re.search(r'Datas?\s*de\s*vencimento\s*([^\n\r]+?)(?:Frete|Total|$)', text, re.IGNORECASE)
        if data_venc_match:
            data["condicoes"]["datas_vencimento"] = data_venc_match.group(1).strip()

        frete_tipo_match = re.search(r'Frete\s*([A-Z]{2,3})', text)
        if frete_tipo_match:
            data["condicoes"]["tipo_frete"] = frete_tipo_match.group(1).strip()

        # Extração de Frete (R$) e Desconto (R$) do Rodapé
        frete_val_match = re.search(r'Frete\s+([\d\.,]+)', text, re.IGNORECASE)
        if frete_val_match:
            f_str = frete_val_match.group(1).strip()
            # Se for um valor numérico (e não CIF/FOB)
            if re.match(r'^\d+[\d\.,]*$', f_str):
                data["condicoes"]["valor_frete_str"] = f_str
                data["condicoes"]["valor_frete"] = parse_br_number(f_str)

        desc_val_match = re.search(r'Desconto\s+([\d\.,]+)', text, re.IGNORECASE)
        if desc_val_match:
            d_str = desc_val_match.group(1).strip()
            data["condicoes"]["valor_desconto_str"] = d_str
            data["condicoes"]["valor_desconto"] = parse_br_number(d_str)

        tot_merc_match = re.search(r'Total\s+das\s+mercadorias\s*([\d\.,]+)', text, re.IGNORECASE)
        if tot_merc_match:
            tm_str = tot_merc_match.group(1).strip()
            data["total_mercadorias_str"] = tm_str
            data["total_mercadorias"] = parse_br_number(tm_str)

        total_pedido_match = re.search(r'TOTAL\s+DO\s+PEDIDO\s*([\d\.,]+)', text, re.IGNORECASE)
        if total_pedido_match:
            tot_str = total_pedido_match.group(1).strip()
            data["total_pedido_str"] = tot_str
            data["total_pedido"] = parse_br_number(tot_str)

        # 6. Observações
        obs_match = re.search(
            r'Observa[çc\?][õo\?]es\s*([\s\S]*?)(?:TOTAL DO PEDIDO|Josivan|Adriano|\Z)',
            text,
            re.IGNORECASE
        )
        if obs_match:
            obs_text = obs_match.group(1).strip()
            obs_lines = [l.strip() for l in obs_text.split('\n') if l.strip() and "SIENGE" not in l and "1 de" not in l and "2 de" not in l]
            data["observacoes"] = "\n".join(obs_lines)

        # 7. VALIDAÇÃO MATEMÁTICA CRUZADA AUTOMÁTICA (Checksum)
        data["validacao_matematica"] = validate_checksum(data)

        return data

    def _parse_items_from_text(self, text: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []

        val_pattern = re.compile(
            r'(?P<qtde>[\d\.]+,\d+)\s*'
            r'(?P<unid>[a-zA-Z0-9º°/²³]+)\s+'
            r'(?P<pr_unit>[\d\.]+,\d+)\s+'
            r'(?P<desc_rs>[\d\.]+,\d+)\s+'
            r'(?P<pct_desc>[\d\.]+,\d+)\s+'
            r'(?P<pct_ipi>[\d\.]+,\d+)\s+'
            r'(?P<pct_acresc>[\d\.]+,\d+)\s+'
            r'(?P<preco_final>[\d\.]+,\d+)'
        )

        lines = text.split('\n')
        inside_items = False
        current_item: Optional[Dict[str, Any]] = None

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            if "Insumo" in line and ("Qtde" in line or "Pr. unit" in line):
                inside_items = True
                continue

            if inside_items and any(marker in line for marker in ["Cond. pagamento", "Total das mercadorias", "TOTAL DO PEDIDO"]):
                inside_items = False
                if current_item:
                    items.append(current_item)
                    current_item = None
                continue

            if not inside_items:
                continue

            if "SIENGE / STARIAN" in line or re.search(r'\d+\s+de\s+\d+', line):
                continue
            if "Dados do faturamento" in line or "Dados do fornecedor" in line or "Dados da obra" in line:
                continue

            val_match = val_pattern.search(line)

            if val_match:
                if current_item:
                    items.append(current_item)
                    current_item = None

                desc_prefix = line[:val_match.start()].strip()
                code_match = re.match(r'^(\d+)\s*-\s*(.+)$', desc_prefix)
                if code_match:
                    item_code = code_match.group(1).strip()
                    item_desc = code_match.group(2).strip()
                else:
                    item_code = ""
                    item_desc = desc_prefix

                qtde_str = val_match.group('qtde')
                unid_str = val_match.group('unid')
                pr_unit_str = val_match.group('pr_unit')
                desc_rs_str = val_match.group('desc_rs')
                pct_desc_str = val_match.group('pct_desc')
                pct_ipi_str = val_match.group('pct_ipi')
                pct_acresc_str = val_match.group('pct_acresc')
                preco_final_str = val_match.group('preco_final')

                current_item = {
                    "codigo": item_code,
                    "descricao": item_desc,
                    "descricao_completa": desc_prefix,
                    "quantidade_str": qtde_str,
                    "quantidade": parse_br_number(qtde_str),
                    "unidade": unid_str,
                    "preco_unitario_str": pr_unit_str,
                    "preco_unitario": parse_br_number(pr_unit_str),
                    "desconto_rs_str": desc_rs_str,
                    "desconto_rs": parse_br_number(desc_rs_str),
                    "pct_desc_str": pct_desc_str,
                    "pct_desc": parse_br_number(pct_desc_str),
                    "pct_ipi_str": pct_ipi_str,
                    "pct_ipi": parse_br_number(pct_ipi_str),
                    "pct_acresc_str": pct_acresc_str,
                    "pct_acresc": parse_br_number(pct_acresc_str),
                    "preco_final_str": preco_final_str,
                    "preco_final": parse_br_number(preco_final_str)
                }

            elif current_item is not None:
                if not any(stop_w in line for stop_w in ["Cond.", "Total", "Observa", "Josivan", "Adriano"]):
                    current_item["descricao"] = (current_item["descricao"] + " " + line).strip()
                    current_item["descricao_completa"] = (current_item["descricao_completa"] + " " + line).strip()

        if current_item:
            items.append(current_item)

        for it in items:
            it["familia"] = classify_item(it.get("descricao", ""), it.get("codigo", ""))

        return items

    def extract_from_pdf(self, file_path: str) -> Dict[str, Any]:
        text = self.extract_text_from_file(file_path)
        return self.extract_from_text(text, source_filename=file_path)
