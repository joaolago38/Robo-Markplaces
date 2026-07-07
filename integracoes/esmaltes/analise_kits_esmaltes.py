"""
integracoes/esmaltes/analise_kits_esmaltes.py
Varredura de kits de esmaltes no ML: vendas, preços e ranking de marcas.
"""
from __future__ import annotations

from typing import Any

from integracoes.esmaltes.analise_mercado import (
    classificar_anuncio,
    padroes_kits,
    ranking_marcas_mercado,
)
from integracoes.marketplaces.busca_multi_marketplace import resumo_por_marketplace


def _eh_kit(anuncio: dict[str, Any]) -> bool:
    if str(anuncio.get("tipo_anuncio") or "") == "kit":
        return True
    qtd = anuncio.get("qtd_kit")
    return bool(qtd and int(qtd) >= 2)


def processar_termo(segmento: dict[str, Any], anuncios: list[dict[str, Any]]) -> dict[str, Any]:
    """Classifica anúncios de um termo e filtra somente kits."""
    classificados = [classificar_anuncio(a) for a in anuncios]
    kits = [a for a in classificados if _eh_kit(a)]
    return {
        "ok": True,
        "id": segmento.get("id"),
        "nome": segmento.get("nome"),
        "termo_busca": segmento.get("termo_busca"),
        "prioridade": int(segmento.get("prioridade") or 99),
        "total_bruto": len(anuncios),
        "total_kits": len(kits),
        "ranking_marcas": ranking_marcas_mercado(kits),
        "kits": kits,
    }


def consolidar_varredura(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrega kits únicos de todos os termos e calcula KPIs globais."""
    por_item: dict[str, dict[str, Any]] = {}
    termos_ok = 0

    for resultado in resultados:
        if not resultado.get("ok"):
            continue
        termos_ok += 1
        for kit in resultado.get("kits") or []:
            iid = str(kit.get("item_id") or "").strip()
            if not iid:
                continue
            atual = por_item.get(iid)
            vendas = int(kit.get("quantidade_vendida") or 0)
            if not atual or vendas > int(atual.get("quantidade_vendida") or 0):
                por_item[iid] = kit

    kits_unicos = list(por_item.values())
    ranking = ranking_marcas_mercado(kits_unicos)
    total_vendas = sum(int(k.get("quantidade_vendida") or 0) for k in kits_unicos)
    precos = [float(k.get("preco") or 0) for k in kits_unicos if float(k.get("preco") or 0) > 0]
    top_vendas = sorted(
        kits_unicos,
        key=lambda x: int(x.get("quantidade_vendida") or 0),
        reverse=True,
    )[:15]

    return {
        "total_kits_unicos": len(kits_unicos),
        "total_vendas": total_vendas,
        "termos_varridos": termos_ok,
        "preco_medio": round(sum(precos) / len(precos), 2) if precos else 0.0,
        "preco_min": round(min(precos), 2) if precos else 0.0,
        "preco_max": round(max(precos), 2) if precos else 0.0,
        "ranking_marcas": ranking[:12],
        "top_vendas": top_vendas,
        "padroes_tamanho": padroes_kits(kits_unicos)[:8],
        "por_marketplace": resumo_por_marketplace(kits_unicos),
    }
