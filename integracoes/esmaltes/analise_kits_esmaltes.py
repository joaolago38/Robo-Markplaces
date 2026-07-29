"""
integracoes/esmaltes/analise_kits_esmaltes.py
Varredura de kits de esmaltes no ML: vendas, preços e ranking de marcas.
"""
from __future__ import annotations

import logging
from typing import Any

from integracoes.esmaltes.analise_mercado import (
    classificar_anuncio,
    padroes_kits,
    ranking_marcas_mercado,
)
from integracoes.marketplaces.busca_multi_marketplace import resumo_por_marketplace

logger = logging.getLogger("analise_kits_esmaltes")


def _eh_kit(anuncio: dict[str, Any]) -> bool:
    if str(anuncio.get("tipo_anuncio") or "") == "kit":
        return True
    qtd = anuncio.get("qtd_kit")
    return bool(qtd and int(qtd) >= 2)


def vendas_tem_dado(anuncio: dict[str, Any] | None) -> bool:
    """True só quando a API informou sold_quantity > 0 (proxy fraco, mas presente)."""
    if not isinstance(anuncio, dict):
        return False
    try:
        return int(anuncio.get("quantidade_vendida") or anuncio.get("sold_quantity") or 0) > 0
    except (TypeError, ValueError):
        return False


def fmt_vendas_proxy(valor: Any, *, sufixo: str = "vendas") -> str:
    """Exibe n/d em vez de '0 vendas' quando a API não informou volume."""
    try:
        n = int(valor or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return "n/d"
    return f"{n} {sufixo}"


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


def _recalcular_kpis(kits_unicos: list[dict[str, Any]], termos_ok: int) -> dict[str, Any]:
    ranking = ranking_marcas_mercado(kits_unicos)
    com_dado = [k for k in kits_unicos if vendas_tem_dado(k)]
    total_vendas = sum(int(k.get("quantidade_vendida") or 0) for k in com_dado)
    precos = [float(k.get("preco") or 0) for k in kits_unicos if float(k.get("preco") or 0) > 0]
    # Prioriza quem tem vendas; se todos n/d, mantém amostra por preço médio estável
    top_vendas = sorted(
        kits_unicos,
        key=lambda x: (
            1 if vendas_tem_dado(x) else 0,
            int(x.get("quantidade_vendida") or 0),
            float(x.get("avaliacoes") or 0),
        ),
        reverse=True,
    )[:15]

    return {
        "total_kits_unicos": len(kits_unicos),
        "total_vendas": total_vendas,
        "kits_com_vendas_api": len(com_dado),
        "vendas_proxy_confiavel": len(com_dado) > 0,
        "termos_varridos": termos_ok,
        "preco_medio": round(sum(precos) / len(precos), 2) if precos else 0.0,
        "preco_min": round(min(precos), 2) if precos else 0.0,
        "preco_max": round(max(precos), 2) if precos else 0.0,
        "ranking_marcas": ranking[:12],
        "top_vendas": top_vendas,
        "padroes_tamanho": padroes_kits(kits_unicos)[:8],
        "por_marketplace": resumo_por_marketplace(kits_unicos),
        "kits_unicos": kits_unicos,
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

    return _recalcular_kpis(list(por_item.values()), termos_ok)


def enriquecer_top_kits(
    consolidado: dict[str, Any],
    *,
    limite: int | None = None,
) -> dict[str, Any]:
    """
    GET /items + reviews nos top N kits da amostra.
    Atualiza sold_quantity/preço quando a API devolver; recalcula KPIs.
    """
    from core.config import ML_ANALISE_ANUNCIO_MAX_ENRIQUECER
    from integracoes.ml import ml_client
    from integracoes.ml.analise_anuncio_concorrente import enriquecer_lista

    max_n = limite if limite is not None else ML_ANALISE_ANUNCIO_MAX_ENRIQUECER
    max_n = max(0, int(max_n))
    kits = list(consolidado.get("kits_unicos") or consolidado.get("top_vendas") or [])
    if not kits or max_n <= 0:
        return consolidado

    # Preferir itens sem venda na busca (precisam de enrich) e depois top por preço
    candidatos = sorted(
        kits,
        key=lambda x: (
            0 if not vendas_tem_dado(x) else 1,
            -float(x.get("preco") or 0),
        ),
    )[:max_n]

    por_id = {str(k.get("item_id") or ""): dict(k) for k in kits if k.get("item_id")}
    for kit in candidatos:
        iid = str(kit.get("item_id") or "").strip()
        if not iid:
            continue
        pub = ml_client.buscar_item_publico(iid)
        if not pub:
            continue
        row = por_id.get(iid) or dict(kit)
        if pub.get("preco"):
            row["preco"] = float(pub["preco"])
        sold = int(pub.get("sold_quantity") or 0)
        if sold > 0:
            row["quantidade_vendida"] = sold
            row["vendas_fonte"] = "items_api"
        row["status"] = pub.get("status") or row.get("status")
        if pub.get("seller_id"):
            row["seller_id"] = pub["seller_id"]
        if pub.get("listing_type_id"):
            row["listing_type_id"] = pub["listing_type_id"]
        por_id[iid] = row

    # Reviews só nos candidatos enriquecidos
    amostra = [por_id[str(c.get("item_id"))] for c in candidatos if c.get("item_id") in por_id]
    try:
        enriquecidos = enriquecer_lista(amostra, limite=len(amostra))
        for e in enriquecidos:
            iid = str(e.get("item_id") or "")
            if iid in por_id:
                por_id[iid] = e
    except Exception as exc:
        logger.warning("enrich reviews kits: %s", exc)

    termos_ok = int(consolidado.get("termos_varridos") or 0)
    out = _recalcular_kpis(list(por_id.values()), termos_ok)
    out["enriquecidos"] = len(candidatos)
    return out


def snapshot_itens_preco(kits: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Mapa item_id → {preco, titulo, status} para histórico entre rodadas."""
    out: dict[str, dict[str, Any]] = {}
    for k in kits or []:
        iid = str(k.get("item_id") or "").strip()
        if not iid:
            continue
        try:
            preco = float(k.get("preco") or 0)
        except (TypeError, ValueError):
            preco = 0.0
        out[iid] = {
            "preco": preco,
            "titulo": str(k.get("titulo") or "")[:80],
            "status": str(k.get("status") or ""),
            "marca": str(k.get("marca") or ""),
        }
    return out


def deltas_preco_itens(
    atuais: dict[str, dict[str, Any]],
    anteriores: dict[str, dict[str, Any]] | None,
    *,
    variacao_alerta_pct: float = 5.0,
    max_linhas: int = 8,
) -> list[str]:
    """
    Sinais de alta confiança: variação de preço e entrada/saída da amostra.
    Não usa vendas (proxy fraco).
    """
    ant = anteriores if isinstance(anteriores, dict) else {}
    linhas: list[str] = []
    ids_atual = set(atuais.keys())
    ids_ant = set(ant.keys())

    for iid in sorted(ids_atual & ids_ant):
        p_now = float((atuais.get(iid) or {}).get("preco") or 0)
        p_old = float((ant.get(iid) or {}).get("preco") or 0)
        if p_now <= 0 or p_old <= 0:
            continue
        var = abs(p_now - p_old) / p_old * 100.0
        if var < variacao_alerta_pct:
            continue
        direcao = "caiu" if p_now < p_old else "subiu"
        titulo = (atuais[iid].get("titulo") or iid)[:40]
        linhas.append(
            f"{titulo}: preço {direcao} R$ {p_old:.2f} → R$ {p_now:.2f} ({var:.1f}%)"
        )

    novos = ids_atual - ids_ant
    sumiram = ids_ant - ids_atual
    if novos and ant:
        linhas.append(f"{len(novos)} anúncio(s) novos na amostra")
    if sumiram and atuais:
        linhas.append(f"{len(sumiram)} anúncio(s) saíram da amostra")

    return linhas[:max_linhas]
