"""
integracoes/veiculos/comparacao.py
Filtra anúncios até preço máximo e compara com FIPE (margem mínima).
"""
from __future__ import annotations

import logging
from typing import Any

from integracoes.veiculos.fipe_client import consultar_preco_fipe

logger = logging.getLogger("veiculos_comparacao")


def calcular_margem_fipe(*, preco_anunciado: float, valor_fipe: float) -> dict[str, float]:
    if valor_fipe <= 0:
        return {"desconto_pct": 0.0, "margem_reais": 0.0}
    margem_reais = valor_fipe - preco_anunciado
    desconto_pct = (margem_reais / valor_fipe) * 100.0
    return {"desconto_pct": round(desconto_pct, 2), "margem_reais": round(margem_reais, 2)}


def avaliar_anuncio(
    anuncio: dict[str, Any],
    *,
    preco_max: float,
    margem_min_pct: float,
    margem_min_reais: float = 0.0,
) -> dict[str, Any] | None:
    preco = float(anuncio.get("preco") or 0)
    if preco <= 0 or preco > preco_max:
        return None

    fipe = consultar_preco_fipe(
        marca=str(anuncio.get("marca") or ""),
        titulo=str(anuncio.get("titulo") or ""),
        ano_texto=str(anuncio.get("ano") or ""),
    )
    if not fipe:
        return None

    margem = calcular_margem_fipe(preco_anunciado=preco, valor_fipe=float(fipe["valor_fipe"]))
    if margem["desconto_pct"] < margem_min_pct:
        return None
    if margem_min_reais > 0 and margem["margem_reais"] < margem_min_reais:
        return None

    return {
        **anuncio,
        **fipe,
        **margem,
        "oportunidade": True,
    }


def filtrar_oportunidades(
    anuncios: list[dict[str, Any]],
    *,
    preco_max: float,
    margem_min_pct: float,
    margem_min_reais: float = 0.0,
) -> list[dict[str, Any]]:
    resultado: list[dict[str, Any]] = []
    for anuncio in anuncios:
        item = avaliar_anuncio(
            anuncio,
            preco_max=preco_max,
            margem_min_pct=margem_min_pct,
            margem_min_reais=margem_min_reais,
        )
        if item:
            resultado.append(item)
    resultado.sort(key=lambda x: float(x.get("desconto_pct") or 0), reverse=True)
    return resultado
