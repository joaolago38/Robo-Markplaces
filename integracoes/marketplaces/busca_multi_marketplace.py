"""
integracoes/marketplaces/busca_multi_marketplace.py
Busca por termo em ML + Magalu + Shopee + Amazon para avaliar desempenho de produtos.
"""
from __future__ import annotations

import logging
from typing import Any

from core.config import MARKETPLACES_BUSCA_ATIVOS

logger = logging.getLogger("busca_multi_marketplace")

_LABELS = {
    "mercadolivre": "Mercado Livre",
    "magalu": "Magalu",
    "shopee": "Shopee",
    "amazon": "Amazon",
}


def marketplaces_ativos() -> list[str]:
    brutos = [m.strip().lower() for m in MARKETPLACES_BUSCA_ATIVOS.split(",") if m.strip()]
    ordem = ("mercadolivre", "magalu", "shopee", "amazon")
    return [m for m in ordem if m in brutos]


def _buscar_ml(termo: str, limite: int) -> list[dict[str, Any]]:
    from integracoes.ml import ml_client

    out: list[dict[str, Any]] = []
    for row in ml_client.buscar_concorrentes_por_termo(termo, limite=limite):
        norm = dict(row)
        norm["marketplace"] = "mercadolivre"
        if not norm.get("fonte_busca"):
            norm["fonte_busca"] = "ml"
        out.append(norm)
    return out


def _buscar_externo(marketplace: str, termo: str, limite: int) -> list[dict[str, Any]]:
    from integracoes.marketplaces.busca_termo_externa import buscar_por_termo

    return buscar_por_termo(marketplace, termo, limite=limite)


def buscar_todos_marketplaces(
    termo: str,
    *,
    limite: int = 25,
    marketplaces: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Varre todos os marketplaces ativos e retorna anúncios deduplicados."""
    termo = (termo or "").strip()
    if not termo:
        return []

    mps = marketplaces or marketplaces_ativos()
    limite = max(1, min(40, limite))
    por_mp = max(5, limite // max(1, len(mps)))

    combinado: list[dict[str, Any]] = []
    vistos: set[str] = set()

    for mp in mps:
        try:
            if mp == "mercadolivre":
                linhas = _buscar_ml(termo, por_mp)
            elif mp in ("magalu", "shopee", "amazon"):
                linhas = _buscar_externo(mp, termo, por_mp)
            else:
                continue
        except Exception as exc:
            logger.warning("Busca %s termo=%r falhou: %s", mp, termo[:50], exc)
            linhas = []

        for row in linhas:
            chave = f"{row.get('marketplace', mp)}:{row.get('item_id') or row.get('permalink') or row.get('titulo')}"
            if chave in vistos:
                continue
            vistos.add(chave)
            combinado.append(row)

    logger.info(
        "Busca multi MP termo=%r → %d anúncio(s) em %s",
        termo[:50],
        len(combinado),
        ",".join(mps),
    )
    return combinado[:limite]


def buscar_fn_multi(termo: str, *, limite: int = 25, item_id_referencia: str | None = None) -> list[dict[str, Any]]:
    """Callable compatível com ml_client.buscar_concorrentes_por_termo."""
    _ = item_id_referencia
    return buscar_todos_marketplaces(termo, limite=limite)


def resolver_fn_busca_esmaltes():
    """Retorna busca multi-MP ou só ML conforme ESMALTES_BUSCA_MULTI_MARKETPLACE."""
    from core.config import ESMALTES_BUSCA_MULTI_MARKETPLACE

    if ESMALTES_BUSCA_MULTI_MARKETPLACE:
        return buscar_fn_multi
    from integracoes.ml import ml_client

    return ml_client.buscar_concorrentes_por_termo


def formatar_secao_por_marketplace(consolidado: dict[str, Any], *, fmt_brl) -> str:
    por_mp = consolidado.get("por_marketplace") or []
    if not por_mp:
        return ""
    linhas = ["", "*Por marketplace*"]
    for mp in por_mp:
        linhas.append(
            f"• {mp.get('label', '?')}: {mp.get('anuncios', 0)} anúncio(s) | "
            f"média {fmt_brl(mp.get('preco_medio'))}"
        )
    return "\n".join(linhas)


def resumo_por_marketplace(anuncios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Estatísticas agregadas por marketplace."""
    buckets: dict[str, dict[str, Any]] = {}
    for an in anuncios:
        mp = str(an.get("marketplace") or "mercadolivre")
        b = buckets.setdefault(
            mp,
            {
                "marketplace": mp,
                "label": _LABELS.get(mp, mp.title()),
                "anuncios": 0,
                "com_preco": 0,
                "vendidos": 0,
                "_precos": [],
            },
        )
        b["anuncios"] += 1
        preco = float(an.get("preco") or 0)
        if preco > 0:
            b["com_preco"] += 1
            b["_precos"].append(preco)
        b["vendidos"] += int(an.get("quantidade_vendida") or 0)

    saida: list[dict[str, Any]] = []
    for item in buckets.values():
        precos = item.pop("_precos", [])
        if precos:
            item["preco_medio"] = round(sum(precos) / len(precos), 2)
            item["preco_min"] = round(min(precos), 2)
            item["preco_max"] = round(max(precos), 2)
        else:
            item["preco_medio"] = 0.0
            item["preco_min"] = 0.0
            item["preco_max"] = 0.0
        saida.append(item)
    saida.sort(key=lambda x: (x["anuncios"], x["vendidos"]), reverse=True)
    return saida
