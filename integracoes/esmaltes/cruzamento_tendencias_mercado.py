"""
integracoes/esmaltes/cruzamento_tendencias_mercado.py
Cruza tendências da web com dados dos marketplaces e gera oportunidades.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from integracoes.esmaltes.analise_mercado import classificar_anuncio, padroes_kits, tendencia_cores
from integracoes.esmaltes.tendencias_internet import coletar_segmento_web
from integracoes.marketplaces.busca_multi_marketplace import resumo_por_marketplace

logger = logging.getLogger("cruzamento_tendencias_mercado")

BuscarFn = Callable[..., list[dict[str, Any]]]


def _score_normalizado(valor: float, maximo: float) -> float:
    if maximo <= 0:
        return 0.0
    return round(min(100.0, 100.0 * valor / maximo), 1)


def _classificar_tendencia(web_score: float, mp_score: float) -> str:
    if web_score >= 40 and mp_score < 25:
        return "oportunidade"
    if web_score >= 30 and mp_score >= 30:
        return "confirmada"
    if mp_score >= 40 and web_score < 20:
        return "saturada_mp"
    if web_score >= 20 or mp_score >= 20:
        return "emergente"
    return "fraca"


def cruzar_sinais(
    web_sinais: dict[str, Any],
    anuncios: list[dict[str, Any]],
    *,
    cores_alvo: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Compara menções web com vendas/preços nos marketplaces por cor."""
    classificados = [classificar_anuncio(a) for a in anuncios]
    mp_cores = tendencia_cores(classificados, top_n=12)

    web_map = {c["cor"].lower(): int(c["mencoes"]) for c in web_sinais.get("cores") or []}
    mp_map = {c["cor"].lower(): int(c["peso_vendas"]) for c in mp_cores}

    alvos = {str(c).lower() for c in (cores_alvo or [])}
    candidatas = set(web_map) | set(mp_map) | alvos

    max_web = max(web_map.values(), default=1)
    max_mp = max(mp_map.values(), default=1)

    tendencias: list[dict[str, Any]] = []
    for cor in candidatas:
        if not cor:
            continue
        mencoes_web = web_map.get(cor, 0)
        peso_mp = mp_map.get(cor, 0)
        web_score = _score_normalizado(mencoes_web, max_web)
        mp_score = _score_normalizado(peso_mp, max_mp)
        status = _classificar_tendencia(web_score, mp_score)
        tendencias.append(
            {
                "cor": cor.title() if cor != "lilás" else "Lilás",
                "mencoes_web": mencoes_web,
                "peso_vendas_mp": peso_mp,
                "score_web": web_score,
                "score_mp": mp_score,
                "status": status,
                "alvo_catalogo": cor in alvos,
            }
        )

    ordem = {"oportunidade": 0, "confirmada": 1, "emergente": 2, "saturada_mp": 3, "fraca": 4}
    tendencias.sort(
        key=lambda t: (
            ordem.get(t["status"], 9),
            -(t["score_web"] + t["score_mp"]),
            -t["mencoes_web"],
        )
    )
    return tendencias


def processar_segmento(
    segmento: dict[str, Any],
    buscar_fn: BuscarFn,
) -> dict[str, Any]:
    """Coleta web + marketplaces e cruza tendências para um segmento."""
    seg_id = str(segmento.get("id") or "?")
    nome = str(segmento.get("nome") or seg_id)
    limite = int(segmento.get("limite_resultados") or 20)
    por_termo = max(5, limite // 2)

    web_sinais = coletar_segmento_web(segmento)

    anuncios: list[dict[str, Any]] = []
    termos_mp_ok: list[str] = []
    for bruto in segmento.get("termos_marketplace") or []:
        termo = str(bruto or "").strip()
        if not termo:
            continue
        try:
            linhas = buscar_fn(termo, limite=por_termo)
        except Exception as exc:
            logger.warning("Busca MP segmento=%s termo=%r: %s", seg_id, termo[:40], exc)
            linhas = []
        if linhas:
            termos_mp_ok.append(termo)
        anuncios.extend(linhas)

    vistos: set[str] = set()
    unicos: list[dict[str, Any]] = []
    for an in anuncios:
        chave = f"{an.get('marketplace', 'ml')}:{an.get('item_id') or an.get('permalink') or an.get('titulo')}"
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(an)

    classificados = [classificar_anuncio(a) for a in unicos]
    tendencias = cruzar_sinais(
        web_sinais,
        unicos,
        cores_alvo=list(segmento.get("cores_alvo") or []),
    )

    return {
        "ok": True,
        "id": seg_id,
        "nome": nome,
        "total_web_hits": web_sinais.get("total_hits", 0),
        "total_anuncios_mp": len(unicos),
        "termos_web_ok": web_sinais.get("termos_varridos") or [],
        "termos_mp_ok": termos_mp_ok,
        "web_sinais": web_sinais,
        "tendencia_cores_mp": tendencia_cores(classificados, top_n=8),
        "padroes_kits_mp": padroes_kits(classificados)[:5],
        "por_marketplace": resumo_por_marketplace(unicos),
        "tendencias": tendencias,
        "top_oportunidades": [t for t in tendencias if t["status"] == "oportunidade"][:5],
        "top_confirmadas": [t for t in tendencias if t["status"] == "confirmada"][:5],
    }


def consolidar_varredura(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrega todos os segmentos em ranking global de tendências."""
    ok = [r for r in resultados if r.get("ok")]
    todas_tendencias: list[dict[str, Any]] = []
    total_web = 0
    total_mp = 0

    for r in ok:
        total_web += int(r.get("total_web_hits") or 0)
        total_mp += int(r.get("total_anuncios_mp") or 0)
        seg_nome = r.get("nome", r.get("id"))
        for t in r.get("tendencias") or []:
            todas_tendencias.append({**t, "segmento": seg_nome, "segmento_id": r.get("id")})

    oportunidades = [t for t in todas_tendencias if t["status"] == "oportunidade"]
    confirmadas = [t for t in todas_tendencias if t["status"] == "confirmada"]
    saturadas = [t for t in todas_tendencias if t["status"] == "saturada_mp"]

    oportunidades.sort(key=lambda x: (-x.get("score_web", 0), -x.get("mencoes_web", 0)))
    confirmadas.sort(key=lambda x: (-(x.get("score_web", 0) + x.get("score_mp", 0)), -x.get("peso_vendas_mp", 0)))
    saturadas.sort(key=lambda x: -x.get("peso_vendas_mp", 0))

    termos_web_agg: dict[str, int] = {}
    for r in ok:
        for item in (r.get("web_sinais") or {}).get("termos") or []:
            termo = str(item.get("termo") or "")
            termos_web_agg[termo] = termos_web_agg.get(termo, 0) + int(item.get("mencoes") or 0)

    top_termos_web = sorted(termos_web_agg.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "segmentos_varridos": len(ok),
        "total_web_hits": total_web,
        "total_anuncios_mp": total_mp,
        "top_oportunidades": oportunidades[:12],
        "top_confirmadas": confirmadas[:10],
        "saturadas_mp": saturadas[:8],
        "top_termos_web": [{"termo": t, "mencoes": n} for t, n in top_termos_web],
        "todas_tendencias": todas_tendencias[:40],
    }
