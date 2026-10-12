"""
integracoes/importacao/normalizar_unidades.py
Normaliza preços Alibaba (por lote/100 peças) e alinha comparação com marketplace BR.
"""
from __future__ import annotations

from typing import Any


def unidade_por_preco(produto: dict[str, Any]) -> int:
    try:
        return max(1, int(produto.get("unidade_por_preco") or 1))
    except (TypeError, ValueError):
        return 1


def unidade_marketplace_qtd(produto: dict[str, Any]) -> int:
    try:
        return max(1, int(produto.get("unidade_marketplace_qtd") or 1))
    except (TypeError, ValueError):
        return 1


def normalizar_preco_usd(produto: dict[str, Any], preco_usd: float) -> dict[str, Any]:
    """Converte preço do listing (ex.: US$ 0,80 / 100 peças) para preço unitário."""
    divisor = unidade_por_preco(produto)
    preco_listing = float(preco_usd)
    preco_unit = preco_listing / divisor
    rotulo = str(produto.get("unidade_rotulo") or "").strip()
    if not rotulo and divisor > 1:
        rotulo = f"{divisor} peças"
    return {
        "preco_usd_listing": round(preco_listing, 6),
        "preco_usd_unit": round(preco_unit, 6),
        "unidade_por_preco": divisor,
        "unidade_rotulo": rotulo or "unidade",
    }


def custo_para_comparacao_marketplace(custo_unitario_brl: float, produto: dict[str, Any]) -> float:
    """Escala custo unitário para o mesmo tamanho de pacote vendido no ML."""
    return round(float(custo_unitario_brl) * unidade_marketplace_qtd(produto), 4)
