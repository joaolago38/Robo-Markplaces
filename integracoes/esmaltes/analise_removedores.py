"""
integracoes/esmaltes/analise_removedores.py
Análise de removedores de unha no ML: nomes, fabricantes e ranking por vendas.
"""
from __future__ import annotations

from typing import Any

from integracoes.esmaltes.analise_acetona_cruzeiro import (
    classificar_listing,
    eh_listing_acetona,
)
from integracoes.marketplaces.busca_multi_marketplace import resumo_por_marketplace

_MARCAS_REMOVEDOR: tuple[str, ...] = (
    "cruzeiro",
    "impala",
    "risque",
    "risqué",
    "colorama",
    "nati",
    "cadiveu",
    "alfaparf",
    "dailus",
    "beira alta",
    "volpe",
    "inove",
    "maria nail",
    "maped",
    "love nails",
    "blant",
    "casalfe",
    "vult",
    "luigi borni",
    "top beauty",
)


def detectar_fabricante(titulo: str) -> str:
    """Identifica fabricante/marca do removedor pelo título."""
    from integracoes.esmaltes.analise_anita import _normalizar

    norm = _normalizar(titulo)
    for marca in _MARCAS_REMOVEDOR:
        if _normalizar(marca) in norm:
            return marca.title() if marca != "risqué" else "Risqué"
    if eh_listing_acetona(titulo):
        return "Genérico/Outros"
    return "Indefinida"


def classificar_removedor(anuncio: dict[str, Any]) -> dict[str, Any]:
    base = classificar_listing(anuncio)
    titulo = str(anuncio.get("titulo") or "")
    fabricante = detectar_fabricante(titulo)
    if fabricante not in ("Indefinida", "Genérico/Outros"):
        base["marca"] = fabricante
        base["fabricante"] = fabricante
    else:
        base["fabricante"] = str(base.get("marca") or fabricante)
    base["nome_produto"] = titulo.strip()[:120]
    return base


def _eh_removedor(anuncio: dict[str, Any]) -> bool:
    return eh_listing_acetona(str(anuncio.get("titulo") or ""))


def processar_termo(
    segmento: dict[str, Any],
    anuncios: list[dict[str, Any]],
    *,
    produtos: list[dict[str, Any]] | None = None,
    termo_usado: str | None = None,
    total_bruto: int | None = None,
) -> dict[str, Any]:
    if produtos is not None:
        classificados = produtos
    else:
        classificados = [classificar_removedor(a) for a in anuncios if _eh_removedor(a)]
    bruto = total_bruto if total_bruto is not None else len(anuncios)
    return {
        "ok": True,
        "id": segmento.get("id"),
        "nome": segmento.get("nome"),
        "termo_busca": segmento.get("termo_busca"),
        "termo_usado": termo_usado or segmento.get("termo_busca"),
        "prioridade": int(segmento.get("prioridade") or 99),
        "total_bruto": bruto,
        "total_removedores": len(classificados),
        "produtos": classificados,
    }


def _ranking_fabricantes(produtos: list[dict[str, Any]], top_n: int = 12) -> list[dict[str, Any]]:
    totais: dict[str, dict[str, Any]] = {}
    for p in produtos:
        fab = str(p.get("fabricante") or p.get("marca") or "Indefinida")
        vendidos = int(p.get("quantidade_vendida") or 0)
        preco = float(p.get("preco") or 0)
        bucket = totais.setdefault(
            fab,
            {"fabricante": fab, "vendidos": 0, "anuncios": 0, "preco_medio": 0.0, "_precos": []},
        )
        bucket["vendidos"] += max(0, vendidos)
        bucket["anuncios"] += 1
        if preco > 0:
            bucket["_precos"].append(preco)

    ranking: list[dict[str, Any]] = []
    for item in totais.values():
        precos = item.pop("_precos", [])
        if precos:
            item["preco_medio"] = round(sum(precos) / len(precos), 2)
        ranking.append(item)
    ranking.sort(key=lambda x: (x["vendidos"], x["anuncios"]), reverse=True)
    for i, item in enumerate(ranking[:top_n], 1):
        item["rank"] = i
    return ranking[:top_n]


def consolidar_varredura(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    por_item: dict[str, dict[str, Any]] = {}
    termos_ok = 0

    for resultado in resultados:
        if not resultado.get("ok"):
            continue
        termos_ok += 1
        for prod in resultado.get("produtos") or []:
            iid = str(prod.get("item_id") or "").strip()
            if not iid:
                continue
            atual = por_item.get(iid)
            vendas = int(prod.get("quantidade_vendida") or 0)
            if not atual or vendas > int(atual.get("quantidade_vendida") or 0):
                por_item[iid] = prod

    produtos_unicos = list(por_item.values())
    ranking = _ranking_fabricantes(produtos_unicos)
    total_vendas = sum(int(p.get("quantidade_vendida") or 0) for p in produtos_unicos)
    precos = [float(p.get("preco") or 0) for p in produtos_unicos if float(p.get("preco") or 0) > 0]

    top_vendas = sorted(
        produtos_unicos,
        key=lambda x: int(x.get("quantidade_vendida") or 0),
        reverse=True,
    )
    for i, p in enumerate(top_vendas[:20], 1):
        p["rank_vendas"] = i

    return {
        "total_produtos_unicos": len(produtos_unicos),
        "total_vendas": total_vendas,
        "termos_varridos": termos_ok,
        "preco_medio": round(sum(precos) / len(precos), 2) if precos else 0.0,
        "preco_min": round(min(precos), 2) if precos else 0.0,
        "preco_max": round(max(precos), 2) if precos else 0.0,
        "ranking_fabricantes": ranking,
        "top_vendas": top_vendas[:15],
        "por_marketplace": resumo_por_marketplace(produtos_unicos),
    }
