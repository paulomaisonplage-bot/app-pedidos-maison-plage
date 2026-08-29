"""
Módulo de Consulta e Inteligência de Dados com Suporte a 43 Famílias, Sugestões e Fluxo de Desembolso Financeiro.
"""

import os
import json
import time
import re
import unicodedata
from typing import List, Dict, Any, Optional, Tuple

from datetime import datetime, date, timedelta
from collections import defaultdict
from src.excel_manager import ExcelManager, check_prazo_status, calculate_installments_for_item, get_week_month_info, NOMES_MESES, get_previous_month_start, clean_family_label, clean_supplier_name, load_verified_suppliers, format_brl, format_qty


def parse_all_dates(date_str: Optional[str]) -> List[date]:
    """Extrai todas as datas válidas dd/mm/aaaa contidas em uma string (suporta múltiplas datas de entrega)."""
    if not date_str:
        return []
    dates = []
    for m in re.findall(r'\b(\d{2}/\d{2}/\d{4})\b', str(date_str)):
        try:
            d = datetime.strptime(m, "%d/%m/%Y").date()
            if d not in dates:
                dates.append(d)
        except Exception:
            pass
    return dates


def parse_date_obj(date_str: Optional[str]) -> Optional[date]:
    """Retorna a primeira data válida de uma string."""
    dates = parse_all_dates(date_str)
    return dates[0] if dates else None


TODAS_43_FAMILIAS = [
    "01 AGREGADOS E AGLOMERANTES",
    "02 ARTEFATOS PREMOLDADOS",
    "03 BLOCOS,TIJOLOS E ELEMENTOS VAZADOS",
    "04 DIVERSOS",
    "05 ALIMENTACAO",
    "06 ALUGUEL DIVERSOS",
    "07 ENERGIA ELÉTRICA - L.T. - S.E.",
    "08 ESQUADRIAS METALICAS",
    "10 EPI'S e EPC'S",
    "11 IMPERMEABILIZANTE-ISOLAMENTO-JUNTAS",
    "12 INSTAL.HIDRAULICA",
    "13 INSTALAÇÕES ELÉTRICAS-TELEFÔNICAS",
    "14 LOUÇAS, METAIS E ACESSORIOS",
    "15 MADEIRA",
    "16 MATERIAL BETUMINOSO - ADITIVOS",
    "18 MISTURAS USINADAS",
    "19 PAISAGISMO",
    "20 PAVIMENTAÇÃO E DRENAGEM",
    "21 PRODUTOS INDUSTRIALIZADOS",
    "23 PRODUTOS METALICOS",
    "24 PVC",
    "25 REVESTIMENTO",
    "26 SERVIÇOS EMPREITADOS",
    "28 INST. DE INCENDIO",
    "29 FERRAGENS",
    "30 MOVEIS E UTENSILIOS",
    "31 ESQUADRIAS DE MADEIRA",
    "33 MATERIAL DE LIMPEZA",
    "34 ARGAMASSAS",
    "35 SINALIZAÇÃO",
    "36 TELHAS",
    "37 TINTAS",
    "38 URBANISMO",
    "39 VEDAÇÃO",
    "42 INST. DE REFRIGERAÇÃO",
    "43 INST. DE GÁS",
    "44 FERRAMENTAS",
    "45 COMBUSTIVEIS",
    "47 MATERIAL DE EXPEDIENTE",
    "01 Equipamentos Aluguel",
    "02 Equipamentos Próprios",
    "01 Verbas, Taxas e Impostos",
    "02 Serviços Terceirizados"
]

SINONIMOS_OBRA = {
    'cano': ['tubo', 'pvc', 'esgoto', 'agua'],
    'canos': ['tubo', 'pvc', 'esgoto', 'agua'],
    'fio': ['cabo', 'flexivel', 'eletrico', 'fios'],
    'fios': ['cabo', 'flexivel', 'eletrico'],
    'bloco': ['tijolo', 'ceramico', 'concreto', 'alvenaria'],
    'blocos': ['tijolo', 'ceramico', 'concreto'],
    'ferro': ['aco', 'metalico', 'barra', 'vergalhao', 'tela'],
    'ferros': ['aco', 'metalico', 'barra', 'vergalhao'],
    'massa': ['argamassa', 'cimento', 'gesso', 'rejunte'],
    'bota': ['botina', 'sapato', 'calcado', 'epi'],
    'botas': ['botina', 'sapato', 'calcado', 'epi'],
    'luva': ['luvas', 'epi', 'protecao'],
    'luvas': ['luva', 'epi', 'protecao'],
    'prego': ['parafuso', 'fixador', 'arame', 'chumbador'],
    'pregos': ['parafuso', 'fixador', 'arame', 'chumbador'],
    'lampadas': ['luminaria', 'led', 'spot', 'plafon']
}


def format_mini_card(
    pc: str,
    p_itens: List[Dict[str, Any]],
    show_group: bool = True,
    hide_financials: bool = False,
    total_order_val: Optional[float] = None,
    highlighted_material: Optional[str] = None,
    more_matches_count: int = 0,
    show_emissao: bool = False
) -> str:
    """
    Formato Universal Nível 1 Padronizado (Limpíssimo e Mobile First):
    📑 PC 12048 • COMERCIAL M B...
    [🎯 MATERIAL DESTACADO]
    [➕ _2 itens_]
    [🏷️ INSTALAÇÕES HIDRÁULICAS]
    [📅 Emissão: DD/MM/AA\n]🚚 DD/MM/AA (Dia)
    📦 17 itens
    💰 R$12.116,50 (quando engenharia)
    """
    fornec_raw = str(p_itens[0].get("fornecedor_nome", "")).strip()
    cnpj_raw = str(p_itens[0].get("fornecedor_cnpj", "")).strip()
    fornec_full = clean_supplier_name(fornec_raw, cnpj=cnpj_raw)
    fornec = (fornec_full[:22] + "...") if len(fornec_full) > 25 else fornec_full
    
    raw_dt = str(p_itens[0].get("data_entrega_prevista", "")).strip()
    dts = parse_all_dates(raw_dt)
    dt_obj = dts[0] if dts else None
    
    dias_semana_abrev = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    if dt_obj:
        dia_sem = f" ({dias_semana_abrev[dt_obj.weekday()]})"
        dt_str = dt_obj.strftime("%d/%m/%y") + dia_sem
    else:
        dt_str = raw_dt[:8] if raw_dt else "A definir"
        
    val_oficial = max((float(i.get("valor_total_pedido", 0.0) or 0.0) for i in p_itens), default=0.0)
    soma_itens = sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in p_itens)
    tot_val = total_order_val if total_order_val is not None else (val_oficial if val_oficial > 0 else soma_itens)
    
    fams = sorted(list(set(clean_family_label(str(i.get("familia_insumo", ""))).upper() for i in p_itens if i.get("familia_insumo"))))
    fam_str = ", ".join(fams)[:32] if fams else ""
    
    itens_count = len(p_itens)
    lbl_itens = "1 item" if itens_count == 1 else f"{itens_count} itens"
    
    linhas = [f"📑 *PC {pc}* • {fornec}"]
    
    if highlighted_material:
        linhas.append(f"🎯 *{highlighted_material.strip()}*")
        if more_matches_count > 0:
            lbl_mais = "1 item" if more_matches_count == 1 else f"{more_matches_count} itens"
            linhas.append(f"➕ _{lbl_mais}_")
            
    if show_group and fam_str:
        linhas.append(f"🏷️ `{fam_str}`")
        
    if show_emissao:
        dt_emissao_raw = str(p_itens[0].get("data_pedido", "")).strip()
        dt_emiss_obj = parse_date_obj(dt_emissao_raw)
        dt_emiss_str = dt_emiss_obj.strftime("%d/%m/%y") if dt_emiss_obj else dt_emissao_raw[:8]
        linhas.append(f"📅 `{dt_emiss_str}`")
        linhas.append(f"🚚 `{dt_str}`")
    else:
        linhas.append(f"🚚 `{dt_str}`")

        
    linhas.append(f"📦 `{lbl_itens}`")
    
    if not hide_financials:
        linhas.append(f"💰 `{format_brl(tot_val)}`")
        
    return "\n".join(linhas) + "\n\n"


def load_all_suppliers_contacts() -> List[Dict[str, Any]]:

    path = os.path.abspath("data/fornecedores_contatos.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


class OrderQueryService:

    _cached_records: Optional[List[Dict[str, Any]]] = None
    _last_mtime: float = 0

    def __init__(self, excel_path: str = "data/pedidos_compra_consolidado.xlsx"):
        self.excel_path = os.path.abspath(excel_path)
        self.manager = ExcelManager(excel_path)

    def _get_all_records(self) -> List[Dict[str, Any]]:
        try:
            current_mtime = os.path.getmtime(self.excel_path)
        except OSError:
            current_mtime = 0

        # Só recarrega o Excel se o arquivo foi modificado no disco ou se o cache estiver vazio
        if OrderQueryService._cached_records is None or current_mtime > OrderQueryService._last_mtime:
            records_dict = self.manager.load_existing_records()
            OrderQueryService._cached_records = list(records_dict.values())
            OrderQueryService._last_mtime = current_mtime
            
        return OrderQueryService._cached_records

    def reload_database(self):
        """Força o recarregamento do banco de dados na memória."""
        OrderQueryService._cached_records = None
        OrderQueryService._last_mtime = 0
        self._get_all_records()

    def get_order_totals_map(self) -> Dict[str, float]:
        records = self._get_all_records()
        totals = defaultdict(float)
        for r in records:
            pc = str(r.get("numero_pedido", "")).strip()
            val = float(r.get("preco_total_item", 0.0) or 0.0)
            totals[pc] += val
        return totals

    def get_all_installments(self, from_previous_month_only: bool = True) -> List[Dict[str, Any]]:
        records = self._get_all_records()
        installments = []
        for r in records:
            insts = calculate_installments_for_item(r)
            installments.extend(insts)

        if from_previous_month_only:
            hoje = datetime.today()
            primeiro_dia_atual = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if primeiro_dia_atual.month == 1:
                mes_corte = primeiro_dia_atual.replace(year=primeiro_dia_atual.year - 1, month=12)
            else:
                mes_corte = primeiro_dia_atual.replace(month=primeiro_dia_atual.month - 1)
            installments = [i for i in installments if i["_venc_dt"] >= mes_corte]

        installments.sort(key=lambda x: x.get("_venc_dt") or datetime.min)
        return installments

    def get_financial_disbursement_by_month(self, from_previous_month_only: bool = True) -> List[Dict[str, Any]]:
        installments = self.get_all_installments(from_previous_month_only=from_previous_month_only)
        mes_map = defaultdict(lambda: {"count": 0, "total_val": 0.0, "pedidos": set()})

        for inst in installments:
            dt_v = inst["_venc_dt"]
            k = (dt_v.year, dt_v.month, inst["mes_ano"])
            mes_map[k]["count"] += 1
            mes_map[k]["total_val"] += inst["valor_parcela"]
            mes_map[k]["pedidos"].add(inst["numero_pedido"])

        resultado = []
        for (ano, mes_num, nome_mes) in sorted(mes_map.keys(), key=lambda x: (x[0], x[1])):
            resultado.append({
                "ano": ano,
                "mes": mes_num,
                "nome_mes": nome_mes,
                "parcelas_count": mes_map[(ano, mes_num, nome_mes)]["count"],
                "pedidos_count": len(mes_map[(ano, mes_num, nome_mes)]["pedidos"]),
                "total_val": mes_map[(ano, mes_num, nome_mes)]["total_val"]
            })
        return resultado

    def get_month_synthesis(self, mes: Optional[int] = None, ano: Optional[int] = None, hide_financials: bool = False) -> str:
        if mes is None or ano is None:
            hoje = date.today()
            mes = hoje.month
            ano = hoje.year

        records = self._get_all_records()
        itens = [r for r in records if parse_date_obj(r.get("data_entrega_prevista")) and parse_date_obj(r.get("data_entrega_prevista")).year == ano and parse_date_obj(r.get("data_entrega_prevista")).month == mes]
        nomes_meses = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        mes_nome = nomes_meses[mes] if 1 <= mes <= 12 else str(mes)

        if not itens:
            return (
                f"🗓️ *SÍNTESE DE ENTREGAS DO MÊS ({mes_nome.upper()}/{ano})*\n\n"
                f"ℹ️ Sem entregas programadas cadastradas para este mês no momento."
            )

        total_val = sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in itens)
        pedidos_set = set(i.get("numero_pedido") for i in itens if i.get("numero_pedido"))

        fam_map = defaultdict(lambda: {"total_val": 0.0, "count": 0})
        for it in itens:
            fam = clean_family_label(str(it.get("familia_insumo", "DIVERSOS")))
            fam_map[fam]["total_val"] += float(it.get("preco_total_item", 0.0) or 0.0)
            fam_map[fam]["count"] += 1

        top_fams = sorted(fam_map.items(), key=lambda x: x[1]["total_val"], reverse=True)[:5]
        linhas_fams = []
        for f_nome, f_info in top_fams:
            if hide_financials:
                linhas_fams.append(f"• *{f_nome}:* `{f_info['count']} itens programados`")
            else:
                f_val = f_info["total_val"]
                pct = (f_val / total_val * 100) if total_val > 0 else 0
                pct_str = f"{pct:.1f}".replace('.', ',')
                linhas_fams.append(f"• *{f_nome}:* `{format_brl(f_val)}` _({pct_str}%)_")

        vol_fin_line = f"💰 *Volume Financeiro:* `{format_brl(total_val)}`\n" if not hide_financials else ""
        txt = (
            f"🗓️ *SÍNTESE DE ENTREGAS DO MÊS ({mes_nome.upper()}/{ano})*\n\n"
            f"{vol_fin_line}"
            f"📦 *Volume Físico:* `{len(itens)} itens` em `{len(pedidos_set)} pedidos de compra`\n\n"
            f"🏢 *Principais Grupos que Chegam neste Mês:*\n" + "\n".join(linhas_fams) + "\n\n"
            f"👇 *Toque em um mês abaixo para visualizar TODOS os pedidos detalhados:*"
        )
        return txt

    def get_delivery_summary_for_month(self, mes: int, ano: int, hide_financials: bool = False, item_offset: int = 0, page_size: int = 4) -> tuple[str, List[str]]:
        """
        Retorna o Panorama Geral de Entregas do Mês (Mini-Cards Nível 1 Padronizados).
        Retorna: (texto_mensagem, lista_de_todos_pcs_para_botoes)
        """
        records = self._get_all_records()
        order_totals_map = self.get_order_totals_map()
        pedidos_map = defaultdict(list)
        total_val = 0.0

        for r in records:
            dts = parse_all_dates(r.get("data_entrega_prevista", ""))
            if any(d.month == mes and d.year == ano for d in dts):
                pc = str(r.get("numero_pedido", "")).strip()
                if pc:
                    pedidos_map[pc].append(r)
                    total_val += float(r.get("preco_total_item", 0.0) or 0.0)

        nomes_meses = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        mes_nome = nomes_meses[mes] if 1 <= mes <= 12 else str(mes)
        ano_2d = str(ano)[-2:]
        hoje = date.today()
        tag_atual = " (Mês Atual)" if (hoje.month == mes and hoje.year == ano) else ""

        if not pedidos_map:
            return (f"ℹ️ *Sem entregas cadastradas para {mes_nome}/{ano_2d}.*", [])

        # Ordenar pedidos por data de entrega mais próxima de hoje e valor
        pedidos_ordenados = sorted(
            pedidos_map.items(),
            key=lambda x: (
                parse_date_obj(x[1][0].get("data_entrega_prevista")) or date.min,
                -sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in x[1])
            )
        )

        total_peds_count = len(pedidos_ordenados)
        lbl_peds = "1 Pedido" if total_peds_count == 1 else f"{total_peds_count} Pedidos"
        
        header_lines = [
            f"🗓️ *{mes_nome.upper()}/{ano_2d}*{tag_atual}",
            f"📊 `{lbl_peds}`"
        ]
        if not hide_financials:
            header_lines.append(f"💰 *Total:* `{format_brl(total_val)}`")
            
        header = "\n".join(header_lines) + "\n\n"

        page_pedidos = pedidos_ordenados[item_offset : item_offset + page_size]
        cards = []
        for pc, p_itens in page_pedidos:
            tot_pc = order_totals_map.get(pc, sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in p_itens))
            cards.append(format_mini_card(pc, p_itens, show_group=True, hide_financials=hide_financials, total_order_val=tot_pc))

        corpo = "".join(cards)
        return (header + corpo, [pc for pc, _ in pedidos_ordenados])



    def get_month_all_materials_detailed(self, mes: int, ano: int, hide_financials: bool = False) -> List[str]:
        records = self._get_all_records()
        order_totals = self.get_order_totals_map()
        itens = []
        for r in records:
            dt = parse_date_obj(r.get("data_entrega_prevista", ""))
            desc = str(r.get("descricao_material") or "").strip()
            cod = str(r.get("codigo_insumo") or "").strip()
            if dt and dt.month == mes and dt.year == ano and (desc or cod):
                itens.append(r)

        nomes_meses = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        mes_nome = nomes_meses[mes] if 1 <= mes <= 12 else str(mes)

        if not itens:
            return [f"ℹ️ *Nenhum insumo detalhado localizado para {mes_nome}/{ano}.*"]

        fam_groups = defaultdict(list)
        total_val = 0.0

        for it in itens:
            fam = clean_family_label(str(it.get("familia_insumo", "DIVERSOS")))
            fam_groups[fam].append(it)
            total_val += float(it.get("preco_total_item", 0.0) or 0.0)

        inv_header = f"📊 *Investimento Total:* `{format_brl(total_val)}` em " if not hide_financials else "📊 "
        header = (
            f"📋 *RELAÇÃO COMPLETA DE INSUMOS - {mes_nome.upper()}/{ano}*\n\n"
            f"{inv_header}`{len(fam_groups)} Grupos` (`{len(itens)} itens`)\n\n"
        )

        sorted_fams = sorted(fam_groups.items(), key=lambda x: len(x[1]) if hide_financials else sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in x[1]), reverse=True)

        blocos = []
        for fam_nome, f_itens in sorted_fams:
            f_tot = sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in f_itens)
            if hide_financials:
                bloco_linhas = [f"🏢 *{fam_nome.upper()}* ({len(f_itens)} itens):"]
            else:
                bloco_linhas = [f"🏢 *{fam_nome.upper()}* (`{format_brl(f_tot)}` • {len(f_itens)} itens):"]

            f_itens_sorted = sorted(f_itens, key=lambda x: str(x.get("descricao_material", "")) if hide_financials else float(x.get("preco_total_item", 0.0) or 0.0), reverse=not hide_financials)
            
            # Limite de itens por família (até 20 itens mais caros como prioridade)
            max_itens_exibidos = 20
            for it in f_itens_sorted[:max_itens_exibidos]:
                desc = str(it.get("descricao_material", "")).strip() or str(it.get("codigo_insumo", ""))
                desc = desc[:45]
                qtde = it.get("quantidade", 0)
                unid = it.get("unidade", "")
                val_it = float(it.get("preco_total_item", 0.0) or 0.0)
                pc = str(it.get("numero_pedido", ""))
                p_tot = order_totals.get(pc, val_it)
                dt_ent = str(it.get("data_entrega_prevista", "")).strip()
                fornec_raw = str(it.get("fornecedor_nome", ""))
                cnpj_raw = str(it.get("fornecedor_cnpj", ""))
                fornec = clean_supplier_name(fornec_raw, cnpj=cnpj_raw)[:24]

                data_str = f" | 📅 Entrega: `{dt_ent}`" if dt_ent else ""
                if hide_financials:
                    bloco_linhas.append(
                        f"• *{desc}*\n"
                        f"  ├ 🔢 Quantidade: `{format_qty(qtde)} {unid}`{data_str}\n"
                        f"  └ 📋 _PC {pc} • {fornec}_\n"
                    )
                else:
                    bloco_linhas.append(
                        f"• *{desc}*\n"
                        f"  ├ 🔢 Quantidade: `{format_qty(qtde)} {unid}`\n"
                        f"  ├ 💰 *Valor do Pedido:* `{format_brl(p_tot)}`{data_str}\n"
                        f"  └ 📋 _PC {pc} • {fornec}_\n"
                    )
            
            if len(f_itens_sorted) > max_itens_exibidos:
                ocultos = len(f_itens_sorted) - max_itens_exibidos
                bloco_linhas.append(f"  └ ➕ _... (+ {ocultos} itens menores ocultos no Telegram)_\n")
                
            blocos.append("\n".join(bloco_linhas))

        messages = []
        current_msg = header
        for b in blocos:
            if len(current_msg) + len(b) > 3600:
                messages.append(current_msg.strip())
                current_msg = f"📋 *INSUMOS DE {mes_nome.upper()}/{ano} (Continuação):*\n\n" + b
            else:
                current_msg += b + "\n\n"

        if current_msg.strip():
            messages.append(current_msg.strip())

        return messages

    def get_delivery_months_overview(self, from_previous_month_only: bool = True) -> List[Dict[str, Any]]:
        records = self._get_all_records()
        meses_map = defaultdict(lambda: {"itens_count": 0, "pedidos": set(), "total_val": 0.0})
        nomes_meses = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        mes_corte = get_previous_month_start()

        for r in records:
            dt = parse_date_obj(r.get("data_entrega_prevista", ""))
            if dt:
                if from_previous_month_only:
                    dt_datetime = datetime.combine(dt, datetime.min.time())
                    if dt_datetime < mes_corte:
                        continue

                k = (dt.year, dt.month)
                meses_map[k]["itens_count"] += 1
                meses_map[k]["pedidos"].add(r.get("numero_pedido"))
                meses_map[k]["total_val"] += float(r.get("preco_total_item", 0.0) or 0.0)

        resultado = []
        for (ano, mes) in sorted(meses_map.keys(), key=lambda x: (x[0], x[1])):
            resultado.append({
                "ano": ano,
                "mes": mes,
                "nome_mes": f"{nomes_meses[mes]}/{ano}",
                "itens_count": meses_map[(ano, mes)]["itens_count"],
                "pedidos_count": len(meses_map[(ano, mes)]["pedidos"]),
                "total_val": meses_map[(ano, mes)]["total_val"]
            })
        return resultado

    def get_financial_schedule_summary(self) -> str:
        """Gera o texto consolidado do Fluxo de Desembolso Financeiro."""
        semanas = self.get_financial_disbursement_next_4_weeks()
        meses = self.get_financial_disbursement_by_month(from_previous_month_only=True)

        rotulos_semanas = {
            'Esta Semana': '(Esta)',
            'Próxima Semana': '(Próx)',
            'Em 2 Semanas': '(Em 2)',
            'Em 3 Semanas': '(Em 3)'
        }

        linhas = [
            "💰 *FLUXO DE DESEMBOLSO FINANCEIRO*\n",
            "📅 *PREVISÃO PRÓXIMAS 4 SEMANAS:*"
        ]

        for s in semanas:
            rotulo_original = s['label']
            rotulo_curto = rotulos_semanas.get(rotulo_original, f"({rotulo_original})")
            periodo = s['periodo']
            val = format_brl(s['total_val'])
            linhas.append(f"• *{periodo}* {rotulo_curto}: `{val}`")

        linhas.append("")

        nomes_meses_abrev = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

        if meses:
            linhas.append("🗓️ *CONSOLIDADO POR MÊS DE VENCIMENTO:*")
            for m in meses[:6]:
                mes_num = m['mes']
                ano_2d = str(m['ano'])[-2:]
                abrev_m = nomes_meses_abrev[mes_num] if 1 <= mes_num <= 12 else str(mes_num)
                val_m = format_brl(m['total_val'])
                linhas.append(f"• *{abrev_m}/{ano_2d}:* `{val_m}`")

        linhas.append("\nℹ️ _Projeção calculada pelas condições de pagamento e prazos de cada pedido cadastrado._")
        return "\n".join(linhas)


    def get_weekly_schedule_summary(self) -> str:
        """Gera o texto consolidado do Cronograma de Entregas Semanais."""
        hoje = date.today()
        semanas_map = {
            "Semana Passada": -1,
            "Esta Semana": 0,
            "Próxima Semana": 1,
            "Em 2 Semanas": 2
        }

        linhas = [
            "🚚 *CRONOGRAMA DE ENTREGAS POR SEMANA - MAISON PLAGE*\n",
            "Selecione uma semana abaixo para ver os pedidos detalhados:\n"
        ]

        for label, offset in semanas_map.items():
            itens = self.get_deliveries_by_week_offset(offset=offset)
            pedidos_set = set(str(it.get("numero_pedido", "")) for it in itens if it.get("numero_pedido"))
            tot_val = sum(float(it.get("preco_total_item", 0.0) or 0.0) for it in itens)
            
            # Período da semana
            inicio_sem = (hoje - timedelta(days=hoje.weekday())) + timedelta(days=offset * 7)
            fim_sem = inicio_sem + timedelta(days=6)
            periodo_str = f"{inicio_sem.strftime('%d/%m')} a {fim_sem.strftime('%d/%m')}"

            linhas.append(f"• *{label}* ({periodo_str}):\n  └ `{len(pedidos_set)} pedidos` • `{len(itens)} itens` • `{format_brl(tot_val)}`\n")

        return "\n".join(linhas)

    def get_deliveries_by_week_offset(self, offset: int = 0) -> List[Dict[str, Any]]:
        """Retorna todos os itens com entrega prevista para uma semana específica (offset relativo à semana atual)."""
        hoje = date.today()
        inicio_sem = (hoje - timedelta(days=hoje.weekday())) + timedelta(days=offset * 7)
        fim_sem = inicio_sem + timedelta(days=6)

        records = self._get_all_records()
        itens_semana = []

        for r in records:
            dts = parse_all_dates(r.get("data_entrega_prevista", ""))
            if any(inicio_sem <= d <= fim_sem for d in dts):
                itens_semana.append(r)

        return sorted(itens_semana, key=lambda x: (parse_date_obj(x.get("data_entrega_prevista")) or date.min, -float(x.get("preco_total_item", 0.0) or 0.0)))

    def get_deliveries_summary_for_week(self, offset: int = 0, hide_financials: bool = False, item_offset: int = 0, page_size: int = 4) -> tuple[str, List[str]]:
        """
        Retorna o Panorama Geral de Entregas da Semana (Mini-Cards Nível 1 Padronizados).
        Retorna: (texto_mensagem, lista_de_todos_pcs_para_botoes)
        """
        hoje = date.today()
        inicio_sem = (hoje - timedelta(days=hoje.weekday())) + timedelta(days=offset * 7)
        fim_sem = inicio_sem + timedelta(days=6)

        nomes_semana = {-1: "Semana Passada", 0: "Esta Semana", 1: "Próxima Semana", 2: "Em 2 Semanas"}
        titulo = nomes_semana.get(offset, "Semana Selecionada")
        periodo_str = f"{inicio_sem.strftime('%d/%m')} a {fim_sem.strftime('%d/%m')}"

        records = self._get_all_records()
        order_totals_map = self.get_order_totals_map()
        pedidos_map = defaultdict(list)
        total_val = 0.0

        for r in records:
            dts = parse_all_dates(r.get("data_entrega_prevista", ""))
            if any(inicio_sem <= d <= fim_sem for d in dts):
                pc = str(r.get("numero_pedido", "")).strip()
                if pc:
                    pedidos_map[pc].append(r)
                    total_val += float(r.get("preco_total_item", 0.0) or 0.0)

        if not pedidos_map:
            return (f"ℹ️ *Nenhum pedido com entrega prevista para {titulo} ({periodo_str}).*", [])

        pedidos_ordenados = sorted(
            pedidos_map.items(),
            key=lambda x: (
                parse_date_obj(x[1][0].get("data_entrega_prevista")) or date.min,
                -sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in x[1])
            )
        )

        total_peds_count = len(pedidos_ordenados)
        lbl_peds = "1 Pedido" if total_peds_count == 1 else f"{total_peds_count} Pedidos"
        
        header_lines = [
            f"🚚 *{titulo.upper()} ({periodo_str})*",
            f"📊 `{lbl_peds}`"
        ]
        if not hide_financials:
            header_lines.append(f"💰 *Total:* `{format_brl(total_val)}`")
            
        header = "\n".join(header_lines) + "\n\n"

        page_pedidos = pedidos_ordenados[item_offset : item_offset + page_size]
        cards = []
        for pc, p_itens in page_pedidos:
            tot_pc = order_totals_map.get(pc, sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in p_itens))
            cards.append(format_mini_card(pc, p_itens, show_group=True, hide_financials=hide_financials, total_order_val=tot_pc))

        corpo = "".join(cards)
        return (header + corpo, [pc for pc, _ in pedidos_ordenados])



    def get_financial_disbursement_next_4_weeks(self, ref_date: Optional[date] = None) -> List[Dict[str, Any]]:
        if ref_date is None:
            ref_date = date.today()

        installments = self.get_all_installments(from_previous_month_only=True)
        hoje = datetime.combine(ref_date, datetime.min.time())
        inicio_esta_semana = hoje - timedelta(days=hoje.weekday())

        semanas_info = []
        labels = ['Esta Semana', 'Próxima Semana', 'Em 2 Semanas', 'Em 3 Semanas']

        for i, label in enumerate(labels):
            ini = inicio_esta_semana + timedelta(days=i * 7)
            fim = ini + timedelta(days=6, hours=23, minutes=59, seconds=59)

            ano_r, mes_r, sem_m, semana_str, periodo_str, _, _ = get_week_month_info(ini + timedelta(days=3))

            parc_sem = [inst for inst in installments if ini <= inst["_venc_dt"] <= fim]
            total_val = sum(p["valor_parcela"] for p in parc_sem)
            peds = len(set(p["numero_pedido"] for p in parc_sem))

            periodo_curto = f"{ini.strftime('%d/%m')} a {fim.strftime('%d/%m')}"
            semanas_info.append({
                "label": label,
                "semana_num": sem_m,
                "mes_nome": NOMES_MESES[mes_r],
                "ano": ano_r,
                "semana_rotulo": f"Sem {sem_m:02d} - {NOMES_MESES[mes_r]}/{ano_r}",
                "periodo": periodo_curto,
                "total_val": total_val,
                "parcelas_count": len(parc_sem),
                "pedidos_count": peds
            })

        return semanas_info

    def get_financial_disbursement_by_week(self, ref_date: Optional[date] = None) -> Dict[str, Any]:
        if ref_date is None:
            ref_date = date.today()

        installments = self.get_all_installments()
        hoje = datetime.combine(ref_date, datetime.min.time())

        # Início e fim da semana atual (Segunda a Domingo)
        inicio_esta_semana = hoje - timedelta(days=hoje.weekday())
        fim_esta_semana = inicio_esta_semana + timedelta(days=6)

        inicio_prox_semana = inicio_esta_semana + timedelta(days=7)
        fim_prox_semana = inicio_prox_semana + timedelta(days=6)

        esta_semana = []
        prox_semana = []

        for inst in installments:
            dt_v = inst["_venc_dt"].replace(hour=0, minute=0, second=0, microsecond=0)
            if inicio_esta_semana <= dt_v <= fim_esta_semana:
                esta_semana.append(inst)
            elif inicio_prox_semana <= dt_v <= fim_prox_semana:
                prox_semana.append(inst)

        return {
            "esta_semana": {
                "periodo": f"{inicio_esta_semana.strftime('%d/%m')} a {fim_esta_semana.strftime('%d/%m/%Y')}",
                "total_val": sum(i["valor_parcela"] for i in esta_semana),
                "parcelas": esta_semana
            },
            "proxima_semana": {
                "periodo": f"{inicio_prox_semana.strftime('%d/%m')} a {fim_prox_semana.strftime('%d/%m/%Y')}",
                "total_val": sum(i["valor_parcela"] for i in prox_semana),
                "parcelas": prox_semana
            }
        }

    def search_by_material(self, query: str) -> List[Dict[str, Any]]:
        records = self._get_all_records()
        clean_q = re.sub(r'[^\w\s]', ' ', query).lower().strip()
        stopwords = {'de', 'e', 'da', 'do', 'em', 'para', 'com', 'sem', 'por', 'um', 'uma', 'os', 'as', 'p'}
        raw_tokens = [t for t in clean_q.split() if t not in stopwords and len(t) >= 2]
        
        if not raw_tokens:
            return []

        expanded = set(raw_tokens)
        for t in raw_tokens:
            if t in SINONIMOS_OBRA:
                expanded.update(SINONIMOS_OBRA[t])
            if t.endswith('s') and len(t) > 3:
                singular = t[:-1]
                expanded.add(singular)
                if singular in SINONIMOS_OBRA:
                    expanded.update(SINONIMOS_OBRA[singular])
            else:
                plural = t + 's'
                expanded.add(plural)
                if plural in SINONIMOS_OBRA:
                    expanded.update(SINONIMOS_OBRA[plural])

        scored = []
        for r in records:
            desc = str(r.get('descricao_material', '')).lower()
            cod = str(r.get('codigo_insumo', '')).lower()
            fam = str(r.get('familia_insumo', '')).lower()
            pc = str(r.get('numero_pedido', '')).lower()

            if cod == clean_q or pc == clean_q:
                scored.append((100, r))
                continue

            score = 0
            for t in raw_tokens:
                if t in desc:
                    score += 5
                elif t in fam or t in cod:
                    score += 2

            for exp in expanded:
                if exp in desc:
                    score += 2
                elif exp in fam:
                    score += 1

            if score > 0:
                scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored]

    def suggest_similar_materials(self, query: str, max_results: int = 4) -> List[Dict[str, str]]:
        records = self._get_all_records()
        clean_q = re.sub(r'[^\w\s]', ' ', query).lower().strip()
        q_tokens = [t for t in clean_q.split() if len(t) >= 2]
        
        if not q_tokens:
            return []

        tokens_expandidos = set(q_tokens)
        for t in q_tokens:
            if t in SINONIMOS_OBRA:
                tokens_expandidos.update(SINONIMOS_OBRA[t])

        catalogo = {}
        for r in records:
            cod = str(r.get("codigo_insumo", "")).strip()
            desc = str(r.get("descricao_material", "")).strip()
            fam = str(r.get("familia_insumo", "04 DIVERSOS")).strip()
            if cod and cod not in catalogo:
                catalogo[cod] = {"codigo": cod, "descricao": desc, "familia": fam}

        scored = []
        for cod, info in catalogo.items():
            desc_l = info["descricao"].lower()
            fam_l = info["familia"].lower()
            score = 0
            for exp in tokens_expandidos:
                if exp in desc_l:
                    score += 3
                elif exp in fam_l:
                    score += 1
                elif len(exp) >= 4 and exp[:4] in desc_l:
                    score += 1
            if score > 0:
                scored.append((score, info))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:max_results]]

    def search_by_family(self, family_query: str) -> List[Dict[str, Any]]:
        records = self._get_all_records()
        clean_q = re.sub(r'[^\w\s]', '', family_query).strip()
        fam_canonical = clean_family_label(clean_q).upper()
        f_lower = fam_canonical.lower().strip()
        matches = []
        for r in records:
            fam = clean_family_label(str(r.get("familia_insumo", ""))).lower()
            if f_lower in fam or fam in f_lower:
                matches.append(r)
        return matches

    def get_family_active_months(self, family_query: str) -> List[Tuple[int, int, str, int]]:
        """Retorna os meses com pedidos ativos para um grupo de insumos: [(ano, mes_num, 'Mês/Ano', count_pedidos)]."""
        clean_q = re.sub(r'[^\w\s]', '', family_query).strip()
        fam_canonical = clean_family_label(clean_q).upper()
        records = self._get_all_records()
        meses_map = defaultdict(set)
        
        for r in records:
            fam_r = clean_family_label(str(r.get("familia_insumo", ""))).upper()
            if fam_canonical == fam_r or clean_q.upper() in fam_r or fam_r in clean_q.upper():
                dt = parse_date_obj(r.get("data_entrega_prevista", ""))
                pc = str(r.get("numero_pedido", "")).strip()
                if dt and pc:
                    meses_map[(dt.year, dt.month)].add(pc)

        res = []
        for (ano, mes) in sorted(meses_map.keys(), reverse=True):
            res.append((ano, mes, f"{NOMES_MESES[mes]}/{ano}", len(meses_map[(ano, mes)])))
        return res

    def get_family_orders_summary(self, family_query: str, hide_financials: bool = False, item_offset: int = 0, page_size: int = 4) -> tuple[str, List[str]]:
        """
        Retorna o Resumo Direto de todos os Pedidos de Compra do Grupo (Mini-Cards Nível 1 Padronizados).
        Retorna: (texto_mensagem, lista_de_todos_pcs_para_botoes)
        """
        clean_q = re.sub(r'[^\w\s]', '', family_query).strip()
        fam_canonical = clean_family_label(clean_q).upper()
        
        def _norm(s: str) -> str:
            return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').upper()

        q_norm = _norm(clean_q)
        records = self._get_all_records()
        matches = []
        for r in records:
            fam_r = clean_family_label(str(r.get("familia_insumo", ""))).upper()
            fam_r_norm = _norm(fam_r)
            if fam_canonical == fam_r or q_norm in fam_r_norm or fam_r_norm in q_norm:
                matches.append(r)
                if fam_canonical == clean_q.upper() and fam_r:
                    fam_canonical = fam_r

        if not matches:
            return (f"ℹ️ *Nenhum pedido de compra localizado para o grupo:* `\"{fam_canonical}\"`.", [])


        # Agrupa os itens por Pedido de Compra (PC)
        pedidos_map = defaultdict(list)
        for it in matches:
            pc = str(it.get("numero_pedido", "")).strip()
            if pc:
                pedidos_map[pc].append(it)

        order_totals_map = self.get_order_totals_map()
        hoje = date.today()

        # Ordena pedidos por proximidade de HOJE
        def _distancia_hoje(item_tuple):
            dt_raw = item_tuple[1][0].get("data_entrega_prevista")
            dt = parse_date_obj(dt_raw)
            if not dt:
                return (2, 9999)
            diff = (dt - hoje).days
            if diff >= 0:
                return (0, diff)      # Futuros ou Hoje primeiro (menor diff)
            return (1, abs(diff))     # Passados depois (mais recentes primeiro)

        pedidos_ordenados = sorted(pedidos_map.items(), key=_distancia_hoje)
        total_peds_count = len(pedidos_ordenados)
        fim_exibidos = min(item_offset + page_size, total_peds_count)
        lbl_peds = f"{item_offset + 1} a {fim_exibidos} de {total_peds_count}" if total_peds_count > page_size else str(total_peds_count)

        header = (
            f"🏢 *{fam_canonical}*\n"
            f"📍 *Próximos* • `{lbl_peds} pedidos`\n\n"
        )


        page_pedidos = pedidos_ordenados[item_offset : item_offset + page_size]
        cards = []
        for pc, p_itens in page_pedidos:
            tot_pc = order_totals_map.get(pc, sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in p_itens))
            cards.append(format_mini_card(pc, p_itens, show_group=False, hide_financials=hide_financials, total_order_val=tot_pc))

        corpo = "".join(cards)
        return (header + corpo, [pc for pc, _ in pedidos_ordenados])

    def search_materials_for_site(self, query: str, hide_financials: bool = False, item_offset: int = 0, page_size: int = 4) -> tuple[str, List[str]]:
        """
        Retorna a busca de materiais padronizada em Mini-Cards (Formato Canteiro de Obras).
        Retorna: (texto_mensagem, lista_de_pcs_desduplicados)
        """
        matches = self.search_by_material(query)
        if not matches:
            return (f"ℹ️ *Nenhum material localizado para a busca:* `\"{query}\"`.", [])

        records = self._get_all_records()
        order_totals_map = self.get_order_totals_map()
        
        all_order_items = defaultdict(list)
        for r in records:
            pc = str(r.get("numero_pedido", "")).strip()
            if pc:
                all_order_items[pc].append(r)

        pc_matches = defaultdict(list)
        for it in matches:
            pc = str(it.get("numero_pedido", "")).strip()
            if pc:
                pc_matches[pc].append(it)

        hoje = date.today()
        def _distancia_entrega(pc_tuple):
            pc = pc_tuple[0]
            p_itens = all_order_items.get(pc, [])
            if not p_itens:
                return (2, 9999)
            dt_raw = p_itens[0].get("data_entrega_prevista")
            dt = parse_date_obj(dt_raw)
            if not dt:
                return (2, 9999)
            diff = (dt - hoje).days
            if diff >= 0:
                return (0, diff)
            return (1, abs(diff))

        pedidos_ordenados = sorted(pc_matches.items(), key=_distancia_entrega)
        total_peds_count = len(pedidos_ordenados)
        
        lbl_peds = "1 Pedido Encontrado" if total_peds_count == 1 else f"{total_peds_count} Pedidos Encontrados"
        header = (
            f"🔍 *RESULTADO DA BUSCA:* `\"{query.upper()}\"`\n"
            f"📄 `{lbl_peds}`\n\n"
        )


        page_pedidos = pedidos_ordenados[item_offset : item_offset + page_size]
        cards = []
        for pc, m_itens in page_pedidos:
            p_all_itens = all_order_items.get(pc, m_itens)
            highlight = str(m_itens[0].get("descricao_material", ""))
            more_count = max(0, len(m_itens) - 1)
            tot_pc = order_totals_map.get(pc, sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in p_all_itens))
            
            cards.append(format_mini_card(
                pc,
                p_all_itens,
                show_group=True,
                hide_financials=hide_financials,
                total_order_val=tot_pc,
                highlighted_material=highlight,
                more_matches_count=more_count
            ))

        corpo = "".join(cards)
        return (header + corpo, [pc for pc, _ in pedidos_ordenados])

    def get_recent_orders_summary(self, max_orders: int = 12, hide_financials: bool = False, item_offset: int = 0, page_size: int = 4) -> tuple[str, List[str]]:
        """
        Retorna as últimas compras emitidas no Sienge no padrão Mini-Card.
        Retorna: (texto_mensagem, lista_de_pcs)
        """
        records = self._get_all_records()
        order_totals_map = self.get_order_totals_map()
        pedidos_map = defaultdict(list)

        for r in records:
            pc = str(r.get("numero_pedido", "")).strip()
            if pc:
                pedidos_map[pc].append(r)

        # Ordenar por data de pedido (emissão) decrescente
        pedidos_ordenados = sorted(
            pedidos_map.items(),
            key=lambda x: parse_date_obj(x[1][0].get("data_pedido")) or date.min,
            reverse=True
        )[:max_orders]

        total_peds_count = len(pedidos_ordenados)
        header = (
            "🛒 *COMPRAS RECENTES*\n"
            f"📍 *Últimos {total_peds_count} Pedidos Emitidos*\n\n"
        )

        page_pedidos = pedidos_ordenados[item_offset : item_offset + page_size]
        cards = []
        for pc, p_itens in page_pedidos:
            tot_pc = order_totals_map.get(pc, sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in p_itens))
            cards.append(format_mini_card(
                pc,
                p_itens,
                show_group=True,
                hide_financials=hide_financials,
                total_order_val=tot_pc,
                show_emissao=True
            ))

        corpo = "".join(cards)
        return (header + corpo, [pc for pc, _ in pedidos_ordenados])

    def get_order_by_number(self, pc_number: str) -> List[Dict[str, Any]]:
        """Retorna todos os itens de um determinado número de pedido (PC)."""
        target = str(pc_number).strip().lower()
        records = self._get_all_records()
        return [r for r in records if str(r.get("numero_pedido", "")).strip().lower() == target]

    def format_full_order_message(self, pc_number: str, page: int = 1, page_size: int = 10, hide_financials: bool = False) -> tuple[str, bool, int, int]:
        """
        Gera a visualização COMPLETA e paginada de um pedido de compra (Nível 2).
        Retorna: (texto_mensagem, has_next_page, page_atual, total_pages)
        """
        itens = self.get_order_by_number(pc_number)
        if not itens:
            return (f"❌ *Pedido PC {pc_number} não foi encontrado na base de dados.*", False, 1, 1)

        # Ordena itens por valor decrescente (ou alfabético se suporte)
        itens_sorted = sorted(
            itens,
            key=lambda x: str(x.get("descricao_material", "")) if hide_financials else float(x.get("preco_total_item", 0.0) or 0.0),
            reverse=not hide_financials
        )

        fornec_raw = str(itens[0].get("fornecedor_nome", "")).strip()
        cnpj_raw = str(itens[0].get("fornecedor_cnpj", "")).strip()
        fornec = clean_supplier_name(fornec_raw, cnpj=cnpj_raw)
        dt_ped = str(itens[0].get("data_pedido", "")).strip()

        dt_ent = str(itens[0].get("data_entrega_prevista", "")).strip()
        raw_cond = str(itens[0].get("condicao_pagamento", "")).strip()
        # Limpa condição de pagamento: remove DIAS e espaços entre barras
        cond_limpa = re.sub(r'\bDIAS\b', '', raw_cond, flags=re.IGNORECASE).strip()
        cond_limpa = re.sub(r'\s*/\s*', '/', cond_limpa)
        cond_limpa = ' '.join(cond_limpa.split())
        cond_pagto = cond_limpa or "Não informada"

        soma_mercadorias = sum(float(i.get("preco_total_item", 0.0) or 0.0) for i in itens)
        val_frete = max((float(i.get("valor_frete", 0.0) or 0.0) for i in itens), default=0.0)
        val_oficial = max((float(i.get("valor_total_pedido", 0.0) or 0.0) for i in itens), default=0.0)
        total_ped = val_oficial if val_oficial > 0 else (soma_mercadorias + val_frete)

        total_itens = len(itens_sorted)
        total_pages = max(1, (total_itens + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * page_size
        end_idx = min(start_idx + page_size, total_itens)
        page_items = itens_sorted[start_idx:end_idx]

        parte_str = f" _(Pág. {page}/{total_pages})_" if total_pages > 1 else ""

        # Grupo principal do pedido (família do primeiro item com mais itens)
        fams = sorted(
            list(set(clean_family_label(str(i.get("familia_insumo", ""))).upper() for i in itens if i.get("familia_insumo"))),
            key=lambda f: sum(1 for i in itens if clean_family_label(str(i.get("familia_insumo", ""))).upper() == f),
            reverse=True
        )
        grupo_principal = fams[0] if fams else "DIVERSOS"

        dt_ped_obj = parse_date_obj(dt_ped)
        dt_ped_str = dt_ped_obj.strftime("%d/%m/%y") if dt_ped_obj else dt_ped[:8]
        
        dt_ent_obj = parse_date_obj(dt_ent)
        dt_ent_str = dt_ent_obj.strftime("%d/%m/%y") if dt_ent_obj else dt_ent[:8]

        header_lines = [
            f"📑 *PC {pc_number}*{parte_str}",
            f"🏷️ `{grupo_principal}`",
            "",
            f"🏢 *{fornec}*",
        ]
        if cnpj_raw:
            header_lines.append(f"📄 CNPJ: `{cnpj_raw}`")

        header_lines.append("")
        header_lines.append(f"📅 `{dt_ped_str}`")
        header_lines.append(f"🚚 `{dt_ent_str}`")

        itens_label = "1 item" if total_itens == 1 else f"{total_itens} itens"
        if not hide_financials:
            if val_frete > 0:
                header_lines.append(f"💰 `{format_brl(soma_mercadorias)} / {format_brl(total_ped)}`")
                header_lines.append(f"🛣️ `{format_brl(val_frete)}`")
            elif val_oficial > soma_mercadorias + 0.05:
                diff_tax = val_oficial - soma_mercadorias
                header_lines.append(f"💰 `{format_brl(soma_mercadorias)} / {format_brl(total_ped)}`")
                header_lines.append(f"🧾 `{format_brl(diff_tax)}`")
            else:
                header_lines.append(f"💰 `{format_brl(total_ped)}`")
            header_lines.append(f"📦 `{itens_label}`")
            header_lines.append(f"💳 `{cond_pagto}`")
        else:
            header_lines.append(f"📦 `{itens_label}`")

        header_lines.append("")
        header_lines.append("📋 *MATERIAIS:*")

        for idx, it in enumerate(page_items, start=start_idx + 1):
            desc = str(it.get("descricao_material", "")).strip() or str(it.get("descricao_completa", "")).strip()
            qtde = float(it.get("quantidade", 0) or 0.0)
            unid = str(it.get("unidade", "")).strip()
            pr_un = float(it.get("preco_unitario", 0.0) or 0.0)
            pr_tot = float(it.get("preco_total_item", 0.0) or 0.0)
            
            header_lines.append(f"*{idx}.* {desc}")
            if hide_financials:
                header_lines.append(f"   🔢 `{format_qty(qtde)}{unid.lower()}`\n")
            else:
                header_lines.append(f"   `{format_qty(qtde)}{unid.lower()} x {format_brl(pr_un)} ➔ {format_brl(pr_tot)}`\n")

        if total_pages > 1:
            header_lines.append(f"📊 _Itens {start_idx + 1}–{end_idx} de {total_itens}._")



        has_next = page < total_pages
        return ("\n".join(header_lines), has_next, page, total_pages)



    def get_all_families_summary(self) -> List[Dict[str, Any]]:
        records = self._get_all_records()
        summary_map = defaultdict(lambda: {"items_count": 0, "total_val": 0.0, "orders": set()})

        for r in records:
            fam = clean_family_label(str(r.get("familia_insumo", "DIVERSOS")).strip())
            val = float(r.get("preco_total_item", 0.0) or 0.0)
            pc = str(r.get("numero_pedido", "")).strip()
            summary_map[fam]["items_count"] += 1
            summary_map[fam]["total_val"] += val
            if pc:
                summary_map[fam]["orders"].add(pc)

        result = []
        for fam_nome, stats in sorted(summary_map.items(), key=lambda x: x[1]["total_val"], reverse=True):
            if stats["items_count"] > 0:
                result.append({
                    "familia": fam_nome,
                    "items_count": stats["items_count"],
                    "orders_count": len(stats["orders"]),
                    "total_val": stats["total_val"]
                })
        return result

    def get_all_suppliers_contacts(self, page: int = 1, page_size: int = 6, query: Optional[str] = None) -> tuple[str, int, int, bool]:

        """
        Retorna a lista paginada de todos os fornecedores (Ordem Alfabética de A a Z).
        Retorna: (texto_mensagem, pagina_atual, total_paginas, tem_proxima)
        """
        catalog = load_all_suppliers_contacts()
        if query:
            clean_q = re.sub(r'[^\w\s]', ' ', query).lower().strip()
            tokens = [t for t in clean_q.split() if len(t) >= 2]
            catalog = [
                f for f in catalog
                if all(t in f["nome"].lower() or t in f.get("vendedor", "").lower() or t in f.get("email", "").lower() for t in tokens)
            ]

        total_items = len(catalog)
        if total_items == 0:
            if query:
                return (f"ℹ️ *Nenhum fornecedor localizado para a busca:* `\"{query}\"`.", 1, 1, False)
            return ("ℹ️ *Nenhum contato de fornecedor disponível.*", 1, 1, False)

        total_pages = max(1, (total_items + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * page_size
        end_idx = min(start_idx + page_size, total_items)
        page_items = catalog[start_idx:end_idx]

        if query:
            header = (
                f"🔍 *RESULTADO DA BUSCA DE CONTATO:* `\"{query.upper()}\"`\n"
                f"📄 `Pág. {page} de {total_pages}`\n\n"
            )
        else:
            header = (
                "📞 *CONTATOS DE FORNECEDORES*\n"
                f"📄 `Pág. {page} de {total_pages}`\n\n"
            )


        cards = []
        for f in page_items:
            card_lines = [f"🏢 *{f['nome']}*"]
            if f.get("vendedor"):
                card_lines.append(f"👤 {f['vendedor']}")
            elif f.get("fone_empresa"):
                card_lines.append(f"📞 {f['fone_empresa']}")
            else:
                card_lines.append("📞 _(Consultar no ERP Sienge)_")

            if f.get("email"):
                card_lines.append(f"✉️ {f['email']}")

            cards.append("\n".join(card_lines))

        corpo = "\n\n".join(cards)
        has_next = page < total_pages
        return (header + corpo, page, total_pages, has_next)


    def get_recent_suppliers_contacts(self, limit: int = 8) -> str:
        msg, _, _, _ = self.get_all_suppliers_contacts(page=1, page_size=limit)
        return msg



    def get_order_by_number(self, pc_number: str) -> List[Dict[str, Any]]:
        """Retorna todos os itens de um determinado número de pedido (PC)."""
        target = str(pc_number).strip().lower()
        records = self._get_all_records()
        return [r for r in records if str(r.get("numero_pedido", "")).strip().lower() == target]


