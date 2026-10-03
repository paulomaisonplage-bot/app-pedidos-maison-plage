"""
Módulo Profundo de Repositório e Consulta de Pedidos de Compra (OrderRepository).
Segue os princípios da metodologia 'codebase-design':
- Interface Enxuta (Small Interface): poucas operações semânticas de alta alavancagem para os controladores.
- Implementação Profunda (Deep Implementation): cache em memória hot (<2ms), carregamento via JSON (<30ms) com fallback transparente para Excel (>3500ms), indexação automática e expansão de busca.
- Seam Limpa: Isola completamente o sistema de arquivos, formato de cache e indexação interna das rotas HTTP.
"""

import os
import json
import time
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple

try:
    from src.excel_manager import ExcelManager, parse_date
    from src.query_service import SINONIMOS_OBRA
except ImportError:
    from excel_manager import ExcelManager, parse_date
    from query_service import SINONIMOS_OBRA

logger = logging.getLogger(__name__)


def get_default_cutoff_date() -> date:
    """Calcula a data limite do primeiro dia do mês anterior."""
    hoje = date.today()
    if hoje.month == 1:
        return date(hoje.year - 1, 12, 1)
    return date(hoje.year, hoje.month - 1, 1)


class OrderRepository:
    def __init__(
        self,
        base_dir: Optional[str] = None,
        excel_path: Optional[str] = None,
        ttl_seconds: float = 180.0
    ):
        if base_dir is None:
            self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        else:
            self.base_dir = os.path.abspath(base_dir)

        if excel_path is None:
            self.excel_path = os.path.join(self.base_dir, "data", "pedidos_compra_consolidado.xlsx")
        else:
            self.excel_path = os.path.abspath(excel_path)

        self.cache_json_path = os.path.join(self.base_dir, "data", "pedidos_cache.json")
        self.ttl_seconds = ttl_seconds

        self._last_load: float = 0
        self._last_mtime: float = 0
        self._raw_records: Dict[Any, Dict[str, Any]] = {}
        self._orders_by_pc: Dict[str, List[Dict[str, Any]]] = {}
        self._catalog_materials: Optional[List[Dict[str, Any]]] = None

    # ---------------------------------------------------------
    # INTERFACE EXTERNA (Alta alavancagem para chamadores)
    # ---------------------------------------------------------

    def get_order(self, pc_num: str) -> Optional[List[Dict[str, Any]]]:
        """Recupera a lista de itens de um pedido pelo número de PC."""
        clean_pc = str(pc_num).strip()
        orders_map = self.get_orders_by_pc()
        return orders_map.get(clean_pc)

    def get_orders_by_pc(self, force_reload: bool = False) -> Dict[str, List[Dict[str, Any]]]:
        """Retorna mapa de pedidos agrupados pelo número de PC com cache transparente."""
        self._ensure_loaded(force_reload)
        return self._orders_by_pc

    def get_raw_records(self, force_reload: bool = False) -> Dict[Any, Dict[str, Any]]:
        """Retorna dicionário de registros brutos de pedidos."""
        self._ensure_loaded(force_reload)
        return self._raw_records

    def search_orders(self, query: str, cutoff_date: Optional[date] = None) -> List[str]:
        """
        Busca pedidos por tokens de busca com expansão de sinônimos da obra.
        Retorna lista ordenada de números de PC encontrados.
        """
        q_clean = query.lower().strip()
        if not q_clean:
            return []

        if cutoff_date is None:
            cutoff_date = get_default_cutoff_date()

        tokens = q_clean.split()
        tokens_exp = set(tokens)
        for t in tokens:
            if t in SINONIMOS_OBRA:
                tokens_exp.update(SINONIMOS_OBRA[t])

        orders_map = self.get_orders_by_pc()
        matching_pcs = set()

        for pc, items in orders_map.items():
            if not items:
                continue
            it0 = items[0]
            dt_ent = (
                parse_date(it0.get("data_entrega_prevista")).date()
                if parse_date(it0.get("data_entrega_prevista"))
                else None
            ) or (
                parse_date(it0.get("data_pedido")).date()
                if parse_date(it0.get("data_pedido"))
                else None
            )

            if dt_ent and dt_ent < cutoff_date:
                continue

            for it in items:
                desc = str(it.get("descricao_material", "") or "").lower()
                cod = str(it.get("codigo_insumo", "") or "").lower()
                fam = str(it.get("familia_insumo", "") or "").lower()

                if any(t in desc or t in cod or t in fam for t in tokens_exp):
                    matching_pcs.add(pc)
                    break

        return sorted(matching_pcs, key=lambda x: int(x) if x.isdigit() else 0, reverse=True)

    def get_orders_by_material(self, material_name: str, cutoff_date: Optional[date] = None) -> List[str]:
        """Busca números de PC que contenham determinado insumo/material."""
        mat_upper = material_name.upper().strip()
        if not mat_upper:
            return []

        if cutoff_date is None:
            cutoff_date = get_default_cutoff_date()

        orders_map = self.get_orders_by_pc()
        matching_pcs = []

        for pc, items in orders_map.items():
            if not items:
                continue
            it0 = items[0]
            dt_ent = (
                parse_date(it0.get("data_entrega_prevista")).date()
                if parse_date(it0.get("data_entrega_prevista"))
                else None
            ) or (
                parse_date(it0.get("data_pedido")).date()
                if parse_date(it0.get("data_pedido"))
                else None
            )

            if dt_ent and dt_ent < cutoff_date:
                continue

            if any(mat_upper == str(i.get("descricao_material", "") or "").strip().upper() for i in items):
                matching_pcs.append(pc)

        return sorted(matching_pcs, key=lambda x: int(x) if x.isdigit() else 0, reverse=True)

    def get_orders_by_family(self, family_name: str) -> List[str]:
        """Busca números de PC pertencentes a determinada família de insumos."""
        fam_upper = family_name.upper().strip()
        if not fam_upper:
            return []

        orders_map = self.get_orders_by_pc()
        matching_pcs = []

        for pc, items in orders_map.items():
            if any(fam_upper in str(i.get("familia_insumo", "") or "").upper() for i in items):
                matching_pcs.append(pc)

        return sorted(matching_pcs, key=lambda x: int(x) if x.isdigit() else 0, reverse=True)

    def get_catalog_materials(
        self,
        letter: Optional[str] = None,
        query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retorna catálogo consolidado de materiais cadastrados,
        com suporte a filtro alfabético e busca por termo.
        """
        all_materials = self._build_or_get_catalog()
        filtered = all_materials

        if letter and letter.upper() != "TODOS":
            l_upper = letter.upper()
            filtered = [i for i in filtered if i["nome"].upper().startswith(l_upper)]

        if query:
            q_l = query.lower().strip()
            filtered = [
                i for i in filtered
                if q_l in i["nome"].lower() or q_l in i["codigo"].lower() or q_l in i["familia"].lower()
            ]

        return {
            "total_cadastrados": len(all_materials),
            "total_filtrados": len(filtered),
            "insumos": filtered[:300]
        }

    def reload(self) -> None:
        """Força a invalidação completa dos caches e recarga do repositório."""
        self._last_load = 0
        self._last_mtime = 0
        self._raw_records.clear()
        self._orders_by_pc.clear()
        self._catalog_materials = None
        self._ensure_loaded(force_reload=True)

    # ---------------------------------------------------------
    # IMPLEMENTAÇÃO INTERNA / ADAPTADORES PRIVADOS
    # ---------------------------------------------------------

    def _ensure_loaded(self, force_reload: bool = False) -> None:
        """Verifica mtime de disco e TTL para carregar ou reutilizar cache em memória."""
        now = time.time()
        current_mtime = self._get_current_mtime()
        mtime_changed = current_mtime > self._last_mtime

        if (
            force_reload
            or mtime_changed
            or (now - self._last_load > self.ttl_seconds)
            or not self._orders_by_pc
        ):
            self._load_from_storage(current_mtime)

    def _get_current_mtime(self) -> float:
        """Obtém o mtime mais recente entre o cache JSON e o Excel."""
        mtime = 0.0
        try:
            if os.path.exists(self.cache_json_path):
                mtime = max(mtime, os.path.getmtime(self.cache_json_path))
            if os.path.exists(self.excel_path):
                mtime = max(mtime, os.path.getmtime(self.excel_path))
        except OSError:
            pass
        return mtime

    def _load_from_storage(self, current_mtime: float) -> None:
        """Carrega dados via adaptador JSON (rápido) com fallback para adaptador Excel."""
        now = time.time()

        # 1. Adaptador JSON (rápido, ~20ms)
        if os.path.exists(self.cache_json_path):
            try:
                with open(self.cache_json_path, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                by_pc = cached_data.get("orders_by_pc", {})
                raw = {}
                for pc, it_list in by_pc.items():
                    for idx, it in enumerate(it_list):
                        item_id = str(it.get("codigo_insumo") or idx)
                        raw[(str(pc), item_id, idx)] = it

                self._raw_records = raw
                self._orders_by_pc = by_pc
                self._last_mtime = current_mtime
                self._last_load = now
                self._catalog_materials = None
                logger.info(f"[OrderRepository] Carregado do cache JSON: {len(by_pc)} pedidos.")
                return
            except Exception as e:
                logger.warning(f"[OrderRepository] Falha ao ler pedidos_cache.json: {e}. Fallback para Excel.")

        # 2. Adaptador Excel (fallback, ~3.5s)
        try:
            manager = ExcelManager(self.excel_path)
            raw = manager.load_existing_records()
            by_pc = {}
            for r in raw.values():
                pc = str(r.get("numero_pedido", "")).strip()
                if pc:
                    if pc not in by_pc:
                        by_pc[pc] = []
                    by_pc[pc].append(r)

            self._raw_records = raw
            self._orders_by_pc = by_pc
            self._last_mtime = current_mtime
            self._last_load = now
            self._catalog_materials = None
            logger.info(f"[OrderRepository] Carregado do Excel: {len(by_pc)} pedidos.")
        except Exception as e:
            logger.error(f"[OrderRepository] Erro ao carregar do Excel: {e}")

    def _build_or_get_catalog(self) -> List[Dict[str, Any]]:
        """Compila e indexa o catálogo de insumos a partir dos registros carregados."""
        if self._catalog_materials is not None:
            return self._catalog_materials

        self._ensure_loaded()
        cutoff = get_default_cutoff_date()
        insumos_map: Dict[str, Dict[str, Any]] = {}

        for r in self._raw_records.values():
            dt_ent = (
                parse_date(r.get("data_entrega_prevista")).date()
                if parse_date(r.get("data_entrega_prevista"))
                else None
            ) or (
                parse_date(r.get("data_pedido")).date()
                if parse_date(r.get("data_pedido"))
                else None
            )

            if not dt_ent or dt_ent < cutoff:
                continue

            desc = str(r.get("descricao_material", "") or "").strip()
            cod = str(r.get("codigo_insumo", "") or "").strip()
            fam = str(r.get("familia_insumo", "04 DIVERSOS") or "04 DIVERSOS").strip()
            pc = str(r.get("numero_pedido", "")).strip()
            qtd = float(r.get("quantidade", 0) or 0.0)
            unid = str(r.get("unidade", "UN") or "UN").strip()

            if not desc and not cod:
                continue

            key = desc.upper() if desc else f"COD_{cod}"
            if key not in insumos_map:
                insumos_map[key] = {
                    "nome": desc if desc else f"Insumo Cód. {cod}",
                    "codigo": cod,
                    "familia": fam,
                    "unidade": unid,
                    "qtd_total": 0.0,
                    "pedidos": set()
                }

            insumos_map[key]["qtd_total"] += qtd
            if pc:
                insumos_map[key]["pedidos"].add(pc)

        sorted_items = sorted(insumos_map.values(), key=lambda x: x["nome"].upper())
        formatted_catalog = []
        for it in sorted_items:
            qtd_fmt = (
                f"{it['qtd_total']:,.1f}"
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
                .rstrip("0")
                .rstrip(",")
            )
            formatted_catalog.append({
                "nome": it["nome"],
                "codigo": it["codigo"],
                "familia": it["familia"],
                "unidade": it["unidade"],
                "qtd_formatada": f"{qtd_fmt} {it['unidade'].lower()}",
                "pedidos_count": len(it["pedidos"]),
                "pedidos": sorted(list(it["pedidos"]), reverse=True)
            })

        self._catalog_materials = formatted_catalog
        return self._catalog_materials
