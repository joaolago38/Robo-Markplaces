# -*- coding: utf-8 -*-
"""
integracoes/esmaltes/metricas_sellers_mercado.py
Top sellers do mercado (Impala / Cruzeiro): vendas/dia na amostra.

A API pública do ML costuma zerar sold_quantity de terceiros. Quando
vendas/dia=0, o ranking cai para transações do perfil (se houver) e
depois quantidade de anúncios na amostra.

Tags: seller:, nick:, rank: — nunca sku:/termo:/item:.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from core.datadog_metrics import gauge
from integracoes.filamentos.metricas_top_anuncios import _f, _i, _tag_nick, _tag_seller
from integracoes.ml.analise_anuncio_concorrente import vendas_por_dia_de_anuncio


def agregar_sellers(
    anuncios: list[dict[str, Any]],
    *,
    sellers_perfil: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, float]]:
    """Soma vendas/dia, vendas e anúncios por seller_id."""
    por_seller: dict[str, dict[str, float]] = defaultdict(
        lambda: {"vendas_dia": 0.0, "vendas": 0.0, "anuncios": 0.0, "com_vpd": 0.0}
    )
    for a in anuncios or []:
        if not isinstance(a, dict):
            continue
        seller = str(a.get("seller_id") or "").strip() or "desconhecido"
        vpd = vendas_por_dia_de_anuncio(a)
        vendas = float(_i(a.get("quantidade_vendida") or a.get("sold_quantity") or a.get("vendas")))
        bucket = por_seller[seller]
        bucket["vendas_dia"] += vpd
        bucket["vendas"] += vendas
        bucket["anuncios"] += 1.0
        if vpd > 0:
            bucket["com_vpd"] += 1.0
    # transações ficam no perfil, não no anúncio
    _ = sellers_perfil
    return dict(por_seller)


def emitir_sellers_mercado(
    prefixo: str,
    anuncios: list[dict[str, Any]],
    *,
    top_n: int = 10,
    sellers_perfil: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Emite gauges por seller (top N).
    prefixo ex.: impala.batalha | cruzeiro.mercado
    """
    prefixo = str(prefixo or "").strip()
    if not prefixo:
        return {"top_sellers": 0, "vendas_dia_amostra": 0}
    perfis = sellers_perfil or {}
    por_seller = agregar_sellers(anuncios or [], sellers_perfil=perfis)
    amostra_vpd = int(sum(b["com_vpd"] for b in por_seller.values()))

    sellers_ord = sorted(
        por_seller.items(),
        key=lambda kv: (
            kv[1]["vendas_dia"],
            _f((perfis.get(kv[0]) or {}).get("transactions_total")),
            kv[1]["vendas"],
            kv[1]["anuncios"],
        ),
        reverse=True,
    )[: max(1, top_n)] if por_seller else []

    max_vpd = 0.0
    for i, (seller, bucket) in enumerate(sellers_ord, 1):
        perfil = perfis.get(seller) or {}
        tags = [_tag_seller(seller), f"rank:{i}"]
        nick = str(perfil.get("nickname") or "").strip()
        if nick:
            tags.append(_tag_nick(nick))
        vpd = float(bucket["vendas_dia"])
        max_vpd = max(max_vpd, vpd)
        gauge(f"{prefixo}.seller_vendas_dia", vpd, tags=tags)
        gauge(f"{prefixo}.seller_vendas", float(bucket["vendas"]), tags=tags)
        gauge(f"{prefixo}.seller_anuncios", float(bucket["anuncios"]), tags=tags)
        txs = _f(perfil.get("transactions_total"))
        if txs:
            gauge(f"{prefixo}.seller_transacoes", txs, tags=tags)

    gauge(f"{prefixo}.seller_vendas_dia_max", max_vpd)
    gauge(f"{prefixo}.vendas_dia_amostra", float(amostra_vpd))
    gauge(f"{prefixo}.top_sellers_emitidos", float(len(sellers_ord)))
    return {
        "top_sellers": len(sellers_ord),
        "vendas_dia_amostra": amostra_vpd,
        "seller_vendas_dia_max": max_vpd,
        "sellers_perfil": len(perfis),
    }
