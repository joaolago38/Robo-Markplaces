"""
integracoes/descoberta/coletores.py
Coleta sinais de mercado por marketplace para análise de nicho e público-alvo.
"""
from __future__ import annotations

import logging
import statistics
from typing import Any

logger = logging.getLogger("descoberta_coletores")


def _termos_do_nicho(nicho: dict[str, Any]) -> list[str]:
    termos: list[str] = []
    for bruto in nicho.get("termos_busca") or []:
        t = str(bruto or "").strip()
        if t:
            termos.append(t)
    unico = str(nicho.get("termo_busca") or "").strip()
    if unico and unico not in termos:
        termos.insert(0, unico)
    return termos[:5]


def _deduplicar_por_item(resultados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vistos: set[str] = set()
    unicos: list[dict[str, Any]] = []
    for row in resultados:
        chave = str(row.get("item_id") or row.get("titulo") or "")
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(row)
    return unicos


def _estatisticas_busca(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    precos = [float(r["preco"]) for r in resultados if float(r.get("preco") or 0) > 0]
    vendidos = [int(r.get("quantidade_vendida") or 0) for r in resultados]
    titulos = [str(r.get("titulo") or "") for r in resultados if r.get("titulo")]
    return {
        "total_anuncios": len(resultados),
        "preco_min": round(min(precos), 2) if precos else None,
        "preco_max": round(max(precos), 2) if precos else None,
        "preco_medio": round(statistics.mean(precos), 2) if precos else None,
        "frete_gratis_pct": round(
            100 * sum(1 for r in resultados if r.get("frete_gratis")) / max(1, len(resultados)),
            1,
        ),
        "vendas_totais_amostra": sum(vendidos),
        "titulos_amostra": titulos[:12],
    }


def coletar_mercadolivre(nicho: dict[str, Any]) -> dict[str, Any]:
    from integracoes.ml import ml_client

    termos = _termos_do_nicho(nicho)
    limite = int(nicho.get("limite_resultados") or 10)
    if not ml_client._enabled():
        return {
            "marketplace": "mercadolivre",
            "configurado": False,
            "termos": termos,
            "motivo": "ML não configurado (token/seller_id)",
        }

    brutos: list[dict[str, Any]] = []
    for termo in termos:
        brutos.extend(ml_client.buscar_concorrentes_por_termo(termo, limite=limite))

    resultados = _deduplicar_por_item(brutos)
    top = sorted(
        resultados,
        key=lambda r: (int(r.get("quantidade_vendida") or 0), float(r.get("preco") or 0)),
        reverse=True,
    )[:8]

    return {
        "marketplace": "mercadolivre",
        "configurado": True,
        "termos": termos,
        "estatisticas": _estatisticas_busca(resultados),
        "top_anuncios": [
            {
                "titulo": r.get("titulo"),
                "preco": r.get("preco"),
                "quantidade_vendida": r.get("quantidade_vendida"),
                "frete_gratis": r.get("frete_gratis"),
                "url": r.get("permalink"),
            }
            for r in top
        ],
    }


def _coletar_saude(marketplace: str) -> dict[str, Any]:
    try:
        if marketplace == "shopee":
            from integracoes.shopee.shopee_client import obter_saude_conta

            return obter_saude_conta()
        if marketplace == "magalu":
            from integracoes.magalu.magalu_client import obter_saude_conta

            return obter_saude_conta()
        if marketplace == "amazon":
            from integracoes.amazon.amazon_client import obter_saude_conta

            return obter_saude_conta()
    except Exception as exc:
        logger.warning("descoberta saúde %s: %s", marketplace, exc)
    return {}


def _cliente_habilitado(marketplace: str) -> bool:
    try:
        if marketplace == "shopee":
            from integracoes.shopee import shopee_client

            return bool(shopee_client._enabled())
        if marketplace == "magalu":
            from integracoes.magalu import magalu_client

            return bool(magalu_client._enabled())
        if marketplace == "amazon":
            from integracoes.amazon import amazon_client

            return bool(amazon_client._enabled())
    except Exception:
        return False
    return False


def coletar_marketplace_generico(marketplace: str, nicho: dict[str, Any]) -> dict[str, Any]:
    """
    Shopee/Magalu/Amazon: sem busca pública por termo no client atual.
    Entrega saúde da conta + termos do nicho para inferência de público pela IA.
    """
    termos = _termos_do_nicho(nicho)
    return {
        "marketplace": marketplace,
        "configurado": _cliente_habilitado(marketplace),
        "termos": termos,
        "busca_por_termo": False,
        "saude_conta": _coletar_saude(marketplace),
        "publico_alvo_hint": str(nicho.get("publico_alvo_hint") or "").strip(),
        "categoria_hint": str(nicho.get("categoria") or "").strip(),
    }


def coletar(marketplace: str, nicho: dict[str, Any]) -> dict[str, Any]:
    mp = (marketplace or "").strip().lower()
    if mp in ("mercadolivre", "ml"):
        return coletar_mercadolivre(nicho)
    if mp in ("shopee", "magalu", "amazon"):
        return coletar_marketplace_generico(mp, nicho)
    return {
        "marketplace": mp,
        "configurado": False,
        "motivo": f"marketplace não suportado: {mp}",
    }
