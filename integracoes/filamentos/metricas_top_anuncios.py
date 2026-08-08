# -*- coding: utf-8 -*-
"""
integracoes/filamentos/metricas_top_anuncios.py
Emite no Datadog top anúncios / sellers (baixa cardinalidade: só top N).

A API pública do ML costuma zerar sold_quantity em buscas de terceiros.
Quando vendas==0, ranqueia por margem_brl / preço e usa porte do seller
(transactions_total do perfil /users/{id}) como proxy de “maior vendedor”.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from core.datadog_metrics import gauge


def _tag_seller(seller_id: str) -> str:
    s = re.sub(r"[^0-9a-z]", "", str(seller_id or "").lower())[:16] or "desconhecido"
    return f"seller:{s}"


def _tag_ad(item_id: str) -> str:
    s = re.sub(r"[^0-9a-z]", "", str(item_id or "").lower())[-12:] or "x"
    return f"ad:{s}"


def _tag_marca(marca: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(marca or "indefinido").lower()).strip("_")[:24] or "x"
    return f"marca:{s}"


def _tag_material(material: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", str(material or "x").lower())[:16] or "x"
    return f"material:{s}"


def _tag_nick(nickname: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(nickname or "").lower()).strip("_")[:28] or "x"
    return f"nick:{s}"


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _i(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _chave_rank_anuncio(p: dict[str, Any]) -> tuple[float, float, float]:
    """Vendas primeiro; se API zerar, margem e preço como proxy de relevância."""
    return (
        float(_i(p.get("quantidade_vendida"))),
        _f(p.get("margem_brl") or p.get("lucro_proxy")),
        _f(p.get("preco")),
    )


def enriquecer_sellers(
    anuncios: list[dict[str, Any]],
    *,
    max_sellers: int = 15,
) -> dict[str, dict[str, Any]]:
    """Busca perfil público dos sellers únicos (transactions / líder)."""
    from integracoes.ml.analise_loja_concorrente import buscar_perfil_loja

    ids: list[str] = []
    vistos: set[str] = set()
    for a in anuncios:
        if not isinstance(a, dict):
            continue
        sid = str(a.get("seller_id") or "").strip()
        if not sid or sid in vistos:
            continue
        vistos.add(sid)
        ids.append(sid)
        if len(ids) >= max_sellers:
            break

    out: dict[str, dict[str, Any]] = {}
    for sid in ids:
        perfil = buscar_perfil_loja(sid)
        if perfil.get("ok"):
            out[sid] = perfil
    return out


def emitir_top_anuncios(
    prefixo: str,
    anuncios: list[dict[str, Any]],
    *,
    top_n: int = 10,
    sellers_perfil: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Emite gauges por anúncio (top vendas/margem) e agrega por seller.
    prefixo ex.: masterprint_petg | filamentos.ml.masterprint
    """
    base = [a for a in anuncios if isinstance(a, dict)]
    ordenados = sorted(base, key=_chave_rank_anuncio, reverse=True)[: max(1, top_n)]

    # Top por margem (sempre — útil quando sold_quantity=0)
    por_margem = sorted(
        base,
        key=lambda p: (_f(p.get("margem_brl") or p.get("lucro_proxy")), _f(p.get("preco"))),
        reverse=True,
    )[: max(1, top_n)]

    por_seller: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "vendas": 0.0,
            "receita": 0.0,
            "anuncios": 0.0,
            "lucro": 0.0,
            "margem": 0.0,
            "preco_min": 0.0,
        }
    )

    for i, p in enumerate(ordenados, 1):
        seller = str(p.get("seller_id") or "").strip()
        tags = [
            _tag_ad(str(p.get("item_id") or "")),
            _tag_seller(seller),
            f"rank:{i}",
            _tag_marca(str(p.get("marca") or "")),
            _tag_material(str(p.get("material") or "")),
        ]
        vendas = float(_i(p.get("quantidade_vendida")))
        preco = _f(p.get("preco"))
        receita = _f(p.get("receita_proxy") or (preco * vendas))
        lucro = _f(p.get("lucro_proxy") or p.get("margem_brl"))
        margem = _f(p.get("margem_brl") or p.get("lucro_proxy"))
        gauge(f"{prefixo}.top_vendas", vendas, tags=tags)
        gauge(f"{prefixo}.top_preco", preco, tags=tags)
        gauge(f"{prefixo}.top_receita", receita, tags=tags)
        if lucro:
            gauge(f"{prefixo}.top_lucro", lucro, tags=tags)
        if margem:
            gauge(f"{prefixo}.top_margem", margem, tags=tags)

        bucket = por_seller[seller or "desconhecido"]
        bucket["vendas"] += vendas
        bucket["receita"] += receita
        bucket["lucro"] += lucro
        bucket["margem"] += margem
        bucket["anuncios"] += 1.0
        if preco > 0 and (bucket["preco_min"] <= 0 or preco < bucket["preco_min"]):
            bucket["preco_min"] = preco

    for i, p in enumerate(por_margem, 1):
        seller = str(p.get("seller_id") or "").strip()
        tags = [
            _tag_ad(str(p.get("item_id") or "")),
            _tag_seller(seller),
            f"rank:{i}",
            _tag_marca(str(p.get("marca") or "")),
            _tag_material(str(p.get("material") or "")),
        ]
        margem = _f(p.get("margem_brl") or p.get("lucro_proxy"))
        gauge(f"{prefixo}.top_margem_rank", margem, tags=tags)
        gauge(f"{prefixo}.top_preco_margem", _f(p.get("preco")), tags=tags)

    # Sellers: prioriza transações do perfil (porte), depois vendas/anúncios
    perfis = sellers_perfil or {}
    sellers_ord = sorted(
        por_seller.items(),
        key=lambda kv: (
            _f((perfis.get(kv[0]) or {}).get("transactions_total")),
            kv[1]["vendas"],
            kv[1]["anuncios"],
            kv[1]["margem"],
        ),
        reverse=True,
    )[: max(1, top_n)]
    for i, (seller, bucket) in enumerate(sellers_ord, 1):
        perfil = perfis.get(seller) or {}
        tags = [_tag_seller(seller), f"rank:{i}"]
        nick = str(perfil.get("nickname") or "").strip()
        if nick:
            tags.append(_tag_nick(nick))
        txs = _f(perfil.get("transactions_total"))
        gauge(f"{prefixo}.seller_vendas", float(bucket["vendas"]), tags=tags)
        gauge(f"{prefixo}.seller_receita", float(bucket["receita"]), tags=tags)
        gauge(f"{prefixo}.seller_anuncios", float(bucket["anuncios"]), tags=tags)
        if bucket["lucro"]:
            gauge(f"{prefixo}.seller_lucro", float(bucket["lucro"]), tags=tags)
        if bucket["margem"]:
            gauge(f"{prefixo}.seller_margem", float(bucket["margem"]), tags=tags)
        if bucket["preco_min"]:
            gauge(f"{prefixo}.seller_preco_min", float(bucket["preco_min"]), tags=tags)
        if txs:
            gauge(f"{prefixo}.seller_transacoes", txs, tags=tags)

    gauge(f"{prefixo}.top_anuncios_emitidos", float(len(ordenados)))
    gauge(f"{prefixo}.top_sellers_emitidos", float(len(sellers_ord)))
    return {
        "top_anuncios": len(ordenados),
        "top_sellers": len(sellers_ord),
        "sellers_perfil": len(perfis),
    }


def emitir_ranking_marcas(
    prefixo: str,
    ranking: list[dict[str, Any]],
    *,
    top_n: int = 12,
) -> None:
    for i, row in enumerate((ranking or [])[:top_n], 1):
        tags = [_tag_marca(str(row.get("marca") or "")), f"rank:{i}"]
        gauge(f"{prefixo}.marca_vendas", float(row.get("vendidos") or 0), tags=tags)
        gauge(f"{prefixo}.marca_anuncios", float(row.get("anuncios") or 0), tags=tags)
        if row.get("preco_medio") is not None:
            gauge(f"{prefixo}.marca_preco_medio", float(row.get("preco_medio") or 0), tags=tags)
