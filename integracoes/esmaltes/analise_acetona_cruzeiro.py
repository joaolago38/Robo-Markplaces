"""
integracoes/esmaltes/analise_acetona_cruzeiro.py
Monitoramento Acetona Cruzeiro no ML: vendedores, margem e contexto Impala/manicures.
"""
from __future__ import annotations

import re
from typing import Any

from core.precificacao_comportamento import calcular_lucro_operacao
from integracoes.esmaltes.analise_anita import _normalizar

_MARCAS_REMOVEDOR = ("cruzeiro", "impala", "risque", "colorama", "nati", "cadiveu", "alfaparf")
_PALAVRAS_ACETONA = ("acetona", "removedor", "remove esmalte", "diluidor")


def detectar_marca_removedor(titulo: str) -> str:
    norm = _normalizar(titulo)
    for marca in _MARCAS_REMOVEDOR:
        if marca in norm:
            return marca.title()
    if any(p in norm for p in _PALAVRAS_ACETONA):
        return "Genérico/Outros"
    return "Indefinida"


def eh_listing_acetona(titulo: str) -> bool:
    norm = _normalizar(titulo)
    return any(p in norm for p in _PALAVRAS_ACETONA)


def eh_cruzeiro(titulo: str) -> bool:
    return "cruzeiro" in _normalizar(titulo)


def extrair_volume_ml(titulo: str) -> int | None:
    norm = _normalizar(titulo)
    m_litro = re.search(r"(\d)\s*litro", norm)
    if m_litro:
        return int(m_litro.group(1)) * 1000
    m_ml = re.search(r"(\d{2,4})\s*ml", norm)
    if m_ml:
        val = int(m_ml.group(1))
        if 30 <= val <= 5000:
            return val
    return None


def classificar_listing(anuncio: dict[str, Any]) -> dict[str, Any]:
    titulo = str(anuncio.get("titulo") or "")
    preco = float(anuncio.get("preco") or 0)
    vol = extrair_volume_ml(titulo)
    ppu = round(preco / vol * 100, 2) if vol and vol > 0 and preco > 0 else None
    return {
        **anuncio,
        "marca": detectar_marca_removedor(titulo),
        "eh_cruzeiro": eh_cruzeiro(titulo),
        "eh_acetona": eh_listing_acetona(titulo),
        "volume_ml": vol,
        "preco_por_100ml": ppu,
    }


def _margem_em_preco(preco: float, custo: float, taxa_pct: float) -> dict[str, Any]:
    if preco <= 0 or custo <= 0:
        return {}
    return calcular_lucro_operacao(preco, custo, taxa_pct)


def analisar_termo(
    item: dict[str, Any],
    anuncios: list[dict[str, Any]],
) -> dict[str, Any]:
    classificados = [classificar_listing(an) for an in anuncios if eh_listing_acetona(str(an.get("titulo") or ""))]
    cruzeiro = [a for a in classificados if a.get("eh_cruzeiro")]
    filtro_vol = item.get("volume_ml")
    if filtro_vol:
        cruzeiro = [a for a in cruzeiro if a.get("volume_ml") == filtro_vol or a.get("volume_ml") is None]

    vendedores = {str(a.get("seller_id") or "") for a in cruzeiro if a.get("seller_id")}
    vendedores.discard("")

    precos = [float(a.get("preco") or 0) for a in cruzeiro if float(a.get("preco") or 0) > 0]
    vendidos = sum(int(a.get("quantidade_vendida") or 0) for a in cruzeiro)

    custo = float(item.get("custo_total") or 0)
    taxa = float(item.get("taxa_marketplace_pct") or 18)
    meu_preco = float(item.get("meu_preco") or 0)

    margens: list[float] = []
    for preco in precos:
        if custo > 0:
            m = _margem_em_preco(preco, custo, taxa)
            if m.get("margem_operacional_pct") is not None:
                margens.append(float(m["margem_operacional_pct"]))

    margem_media_mercado = round(sum(margens) / len(margens), 1) if margens else None
    margem_minha = _margem_em_preco(meu_preco, custo, taxa) if meu_preco > 0 and custo > 0 else {}

    marcas: dict[str, int] = {}
    for a in classificados:
        m = str(a.get("marca") or "?")
        marcas[m] = marcas.get(m, 0) + 1

    kits_impala = [
        a
        for a in classificados
        if _normalizar(str(a.get("marca") or "")) == "impala" and "kit" in _normalizar(str(a.get("titulo") or ""))
    ]

    return {
        "id": item.get("id"),
        "nome": item.get("nome"),
        "termo_busca": item.get("termo_busca"),
        "total_anuncios_busca": len(anuncios),
        "total_acetona": len(classificados),
        "total_cruzeiro": len(cruzeiro),
        "vendedores_cruzeiro": len(vendedores),
        "vendedores_ids": sorted(vendedores)[:50],
        "unidades_vendidas_cruzeiro": vendidos,
        "preco_medio_cruzeiro": round(sum(precos) / len(precos), 2) if precos else None,
        "preco_min_cruzeiro": round(min(precos), 2) if precos else None,
        "preco_max_cruzeiro": round(max(precos), 2) if precos else None,
        "margem_media_mercado_pct": margem_media_mercado,
        "margem_minha": margem_minha,
        "meu_preco": meu_preco or None,
        "custo_total": custo or None,
        "ranking_marcas": sorted(
            [{"marca": k, "anuncios": v} for k, v in marcas.items()],
            key=lambda x: x["anuncios"],
            reverse=True,
        ),
        "kits_impala_no_termo": len(kits_impala),
        "destaques_cruzeiro": sorted(
            cruzeiro,
            key=lambda x: int(x.get("quantidade_vendida") or 0),
            reverse=True,
        )[:5],
        "ok": bool(cruzeiro or classificados),
    }


def consolidar_acetona(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in resultados if r.get("ok")]
    vendedores_global: set[str] = set()
    for r in ok:
        vendedores_global.update(r.get("vendedores_ids") or [])

    margens = [r["margem_media_mercado_pct"] for r in ok if r.get("margem_media_mercado_pct") is not None]
    precos = [r["preco_medio_cruzeiro"] for r in ok if r.get("preco_medio_cruzeiro")]
    vendidos = sum(int(r.get("unidades_vendidas_cruzeiro") or 0) for r in ok)

    return {
        "total_termos": len(resultados),
        "termos_com_dados": len(ok),
        "vendedores_cruzeiro_unicos": len(vendedores_global),
        "unidades_vendidas_cruzeiro": vendidos,
        "margem_media_mercado_pct": round(sum(margens) / len(margens), 1) if margens else None,
        "preco_medio_cruzeiro": round(sum(precos) / len(precos), 2) if precos else None,
        "resultados": ok,
    }


def resumir_impala_para_claude(produtos: list[dict[str, Any]], *, limite: int = 8) -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    for p in produtos:
        sku = str(p.get("sku") or "")
        if not sku.upper().startswith(("IMP-", "KIT-", "BUNDLE-")):
            continue
        ml = (p.get("canais") or {}).get("mercadolivre") or {}
        if not ml.get("ativo"):
            continue
        custo = float(p.get("custo_total") or 0)
        preco = float(ml.get("preco") or p.get("preco") or 0)
        margem = calcular_lucro_operacao(preco, custo, 18) if preco > 0 and custo > 0 else {}
        saida.append(
            {
                "sku": sku,
                "nome": p.get("nome"),
                "preco_ml": preco,
                "custo_total": custo,
                "margem_pct": margem.get("margem_operacional_pct"),
                "fase": p.get("fase_atual"),
            }
        )
        if len(saida) >= limite:
            break
    return saida


def carregar_manicures_brasil(caminho_relativo: str) -> dict[str, Any]:
    from core.atomic_io import ler_json
    from core.config import ROOT

    return ler_json(ROOT / caminho_relativo, default={})
