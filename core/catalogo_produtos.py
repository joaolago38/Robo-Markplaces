"""
core/catalogo_produtos.py
Carrega catalogo/produtos.json e mescla custo/estoque do Bling quando disponível.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from core.config import ROOT

logger = logging.getLogger("catalogo_produtos")

CATALOGO_PATH = ROOT / "catalogo" / "produtos.json"


def carregar_produtos_catalogo() -> list[dict[str, Any]]:
    try:
        if not CATALOGO_PATH.is_file():
            logger.warning("catalogo/produtos.json não encontrado")
            return []
        data = json.loads(CATALOGO_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.error("Erro ao carregar produtos.json: %s", exc)
        return []


def _custo_do_produto(produto: dict[str, Any], bling: dict[str, Any] | None) -> float:
    for chave in ("custo_total", "custo"):
        try:
            v = float(produto.get(chave) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    if bling:
        try:
            return float(bling.get("custo") or 0)
        except (TypeError, ValueError):
            pass
    return 0.0


def carregar_produtos_para_operacao(*, merge_bling: bool = True) -> list[dict[str, Any]]:
    """
    Lista de produtos com canais do catálogo + custo atualizado do Bling.
    Usado por repricing, inteligência de preços e sincronização.
    """
    catalogo = carregar_produtos_catalogo()
    if not catalogo:
        return []

    bling_por_sku: dict[str, dict[str, Any]] = {}
    if merge_bling:
        try:
            from integracoes.bling.bling_client import listar_produtos_por_sku

            bling_por_sku = listar_produtos_por_sku()
        except Exception as exc:
            logger.warning("catalogo: Bling indisponível para merge: %s", exc)

    resultado: list[dict[str, Any]] = []
    for produto in catalogo:
        if not isinstance(produto, dict):
            continue
        sku = str(produto.get("sku") or "").strip()
        if not sku:
            continue
        bling = bling_por_sku.get(sku)
        custo = _custo_do_produto(produto, bling)
        merged = dict(produto)
        merged["sku"] = sku
        merged["custo"] = custo
        if bling:
            merged["estoque_bling"] = bling.get("estoque")
            if not merged.get("nome"):
                merged["nome"] = bling.get("nome")
        resultado.append(merged)
    return resultado
