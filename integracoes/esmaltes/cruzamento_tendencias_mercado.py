"""
integracoes/esmaltes/cruzamento_tendencias_mercado.py
Cruza tendências da web com dados dos marketplaces e gera oportunidades.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from integracoes.esmaltes.analise_anita import _normalizar
from integracoes.esmaltes.analise_mercado import (
    classificar_anuncio,
    padroes_kits,
    tendencia_cores,
    vendas_api,
    volume_proxy_anuncio,
)
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

    web_map: dict[str, int] = {}
    for c in web_sinais.get("cores") or []:
        if not isinstance(c, dict):
            continue
        cor = str(c.get("cor") or "").strip().lower()
        if not cor:
            continue
        try:
            mencoes = int(c.get("mencoes") if c.get("mencoes") is not None else c.get("mencoes_web") or 0)
        except (TypeError, ValueError):
            mencoes = 0
        web_map[cor] = web_map.get(cor, 0) + mencoes
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
            ordem.get(t.get("status"), 9),
            -(float(t.get("score_web") or 0) + float(t.get("score_mp") or 0)),
            -int(t.get("mencoes_web") or 0),
        )
    )
    return tendencias


_STATUS_BONUS = {
    "confirmada": 40,
    "oportunidade": 35,
    "emergente": 18,
    "saturada_mp": 8,
    "fraca": 0,
    "sem_tendencia": 0,
}
_STATUS_ORDEM = {
    "confirmada": 0,
    "oportunidade": 1,
    "emergente": 2,
    "saturada_mp": 3,
    "fraca": 4,
    "sem_tendencia": 5,
}
_MARCAS_IGNORAR = frozenset({"outros", "indefinida", ""})


def _slug_marca(marca: str) -> str:
    return _normalizar(marca).replace(" ", "_") or "indefinida"


def _status_melhor(a: str, b: str) -> str:
    oa = _STATUS_ORDEM.get(a, 9)
    ob = _STATUS_ORDEM.get(b, 9)
    return a if oa <= ob else b


def _mapa_status_cor(tendencias: list[dict[str, Any]] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for t in tendencias or []:
        if not isinstance(t, dict):
            continue
        cor = _normalizar(str(t.get("cor") or ""))
        if not cor:
            continue
        st = str(t.get("status") or "fraca")
        out[cor] = _status_melhor(out.get(cor, "sem_tendencia"), st)
    return out


def _enriquecer_anuncio(anuncio: dict[str, Any]) -> dict[str, Any]:
    """Classifica o título e aplica marca/qtd/cores já detectadas no snapshot."""
    c = classificar_anuncio(anuncio)
    marca_hint = anuncio.get("marca_detectada")
    if marca_hint and _slug_marca(str(marca_hint)) not in _MARCAS_IGNORAR:
        c["marca"] = str(marca_hint)
    qtd_hint = anuncio.get("qtd_kit_detectada")
    if qtd_hint:
        try:
            c["qtd_kit"] = int(qtd_hint)
        except (TypeError, ValueError):
            pass
    cores_hint = anuncio.get("cores_encontradas") or []
    if cores_hint:
        existing = [str(x) for x in (c.get("cores_detectadas") or []) if x]
        for cor in cores_hint:
            s = str(cor).strip()
            if s and s not in existing:
                existing.append(s)
        c["cores_detectadas"] = existing
    return c


def cruzar_marca_kit_tendencia(
    anuncios: list[dict[str, Any]],
    tendencias: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Marca × quantidade do kit × tendência. Identifica ofertas com condição e desempenho ML."""
    classificados = [_enriquecer_anuncio(a) for a in anuncios]
    cor_status = _mapa_status_cor(tendencias)
    buckets: dict[tuple[str, int], dict[str, Any]] = {}
    for an in classificados:
        marca = str(an.get("marca") or "")
        slug = _slug_marca(marca)
        if slug in _MARCAS_IGNORAR:
            continue
        qtd = int(an.get("qtd_kit") or 0)
        if qtd < 2:
            continue
        chave = (slug, qtd)
        b = buckets.setdefault(
            chave,
            {
                "marca": marca.title() if marca.islower() else marca,
                "slug": slug,
                "qtd_kit": qtd,
                "vendidos": 0,
                "volume_proxy": 0,
                "anuncios": 0,
                "preco_medio": 0.0,
                "preco_por_unidade": 0.0,
                "_precos": [],
                "_cores": {},
            },
        )
        b["vendidos"] += vendas_api(an)
        proxy, _ = volume_proxy_anuncio(an)
        b["volume_proxy"] += proxy
        b["anuncios"] += 1
        preco = float(an.get("preco") or 0)
        if preco > 0:
            b["_precos"].append(preco)
        for cor in an.get("cores_detectadas") or []:
            cnorm = _normalizar(str(cor))
            if cnorm:
                b["_cores"][cnorm] = b["_cores"].get(cnorm, 0) + 1

    ranking: list[dict[str, Any]] = []
    for item in buckets.values():
        precos = item.pop("_precos", [])
        cores_cnt = item.pop("_cores", {})
        if precos:
            item["preco_medio"] = round(sum(precos) / len(precos), 2)
            item["preco_por_unidade"] = round(item["preco_medio"] / item["qtd_kit"], 2)
        status = "sem_tendencia"
        cores_tend: list[str] = []
        for cor, _n in sorted(cores_cnt.items(), key=lambda x: -x[1]):
            st = cor_status.get(cor)
            if not st:
                continue
            cores_tend.append(cor.title())
            status = _status_melhor(status, st)
        item["cores_tendencia"] = cores_tend[:4]
        item["status_tendencia"] = status
        condicao_ok = item["qtd_kit"] >= 3 and item["preco_medio"] > 0 and (
            item["anuncios"] >= 2 or item["vendidos"] > 0 or item["volume_proxy"] >= 5
        )
        item["condicao_ok"] = condicao_ok
        item["performance_boa"] = bool(
            condicao_ok and status in ("confirmada", "oportunidade", "emergente")
        )
        item["score"] = int(
            item["vendidos"] * 10
            + item["volume_proxy"]
            + item["anuncios"] * 2
            + _STATUS_BONUS.get(status, 0)
            + (15 if condicao_ok else 0)
        )
        ranking.append(item)
    ranking.sort(
        key=lambda x: (
            bool(x.get("performance_boa")),
            x["score"],
            x["vendidos"],
            x["anuncios"],
        ),
        reverse=True,
    )
    return ranking


def _fundir_marca_kit(listas: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, int], dict[str, Any]] = {}
    for lista in listas:
        for row in lista:
            if not isinstance(row, dict):
                continue
            slug = str(row.get("slug") or _slug_marca(str(row.get("marca") or "")))
            qtd = int(row.get("qtd_kit") or 0)
            if not slug or qtd < 2 or slug in _MARCAS_IGNORAR:
                continue
            b = buckets.setdefault(
                (slug, qtd),
                {
                    "marca": row.get("marca") or slug,
                    "slug": slug,
                    "qtd_kit": qtd,
                    "vendidos": 0,
                    "volume_proxy": 0,
                    "anuncios": 0,
                    "preco_medio": 0.0,
                    "preco_por_unidade": 0.0,
                    "cores_tendencia": [],
                    "status_tendencia": "sem_tendencia",
                    "condicao_ok": False,
                    "performance_boa": False,
                    "score": 0,
                    "_precos": [],
                },
            )
            b["vendidos"] += int(row.get("vendidos") or 0)
            b["volume_proxy"] += int(row.get("volume_proxy") or 0)
            b["anuncios"] += int(row.get("anuncios") or 0)
            if float(row.get("preco_medio") or 0) > 0:
                b["_precos"].append(float(row["preco_medio"]))
            for cor in row.get("cores_tendencia") or []:
                if cor not in b["cores_tendencia"]:
                    b["cores_tendencia"].append(cor)
            b["status_tendencia"] = _status_melhor(
                str(b.get("status_tendencia") or "sem_tendencia"),
                str(row.get("status_tendencia") or "sem_tendencia"),
            )
    saida: list[dict[str, Any]] = []
    for item in buckets.values():
        precos = item.pop("_precos", [])
        if precos:
            item["preco_medio"] = round(sum(precos) / len(precos), 2)
            item["preco_por_unidade"] = round(item["preco_medio"] / item["qtd_kit"], 2)
        item["condicao_ok"] = item["qtd_kit"] >= 3 and item["preco_medio"] > 0 and (
            item["anuncios"] >= 2 or item["vendidos"] > 0 or item["volume_proxy"] >= 5
        )
        item["performance_boa"] = bool(
            item["condicao_ok"]
            and item["status_tendencia"] in ("confirmada", "oportunidade", "emergente")
        )
        item["score"] = int(
            item["vendidos"] * 10
            + item["volume_proxy"]
            + item["anuncios"] * 2
            + _STATUS_BONUS.get(str(item["status_tendencia"]), 0)
            + (15 if item["condicao_ok"] else 0)
        )
        saida.append(item)
    saida.sort(
        key=lambda x: (bool(x.get("performance_boa")), x["score"], x["vendidos"]),
        reverse=True,
    )
    return saida


def tendencias_de_snapshot(blob: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from core.atomic_io import ler_json
    from core.config import ROOT

    data = blob if blob is not None else ler_json(ROOT / "logs" / "esmaltes_tendencias_ultima.json", default={})
    if not isinstance(data, dict):
        return []
    cons = data.get("consolidado") if isinstance(data.get("consolidado"), dict) else data
    out: list[dict[str, Any]] = []
    for chave in ("todas_tendencias", "top_confirmadas", "top_oportunidades", "tendencias"):
        raw = cons.get(chave) if isinstance(cons, dict) else None
        if isinstance(raw, list):
            out.extend(x for x in raw if isinstance(x, dict))
    return out


def anuncios_de_snapshots(
    *,
    mercado: dict[str, Any] | None = None,
    anita: dict[str, Any] | None = None,
    kits: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Reconstrói anúncios classificados a partir dos snapshots já coletados."""
    from core.atomic_io import ler_json
    from core.config import ROOT

    if mercado is None:
        mercado = ler_json(ROOT / "logs" / "esmaltes_mercado_ultima.json", default={})
    if anita is None:
        anita = ler_json(ROOT / "logs" / "anita_esmaltes_ultima.json", default={})
    if kits is None:
        kits = ler_json(ROOT / "logs" / "esmaltes_kits_monitor_ultima.json", default={})
    bruto: list[dict[str, Any]] = []
    if isinstance(mercado, dict):
        cons = mercado.get("consolidado") if isinstance(mercado.get("consolidado"), dict) else {}
        bruto.extend(cons.get("top_anuncios") or [])
        for seg in mercado.get("segmentos") or []:
            if isinstance(seg, dict):
                bruto.extend(seg.get("destaques") or [])
    if isinstance(anita, dict):
        for row in anita.get("resultados") or []:
            if not isinstance(row, dict):
                continue
            for an in row.get("analises") or []:
                if not isinstance(an, dict):
                    continue
                bruto.append(
                    {
                        "titulo": an.get("titulo"),
                        "preco": an.get("preco") or an.get("preco_anuncio"),
                        "quantidade_vendida": an.get("quantidade_vendida"),
                        "marca_detectada": an.get("marca_detectada") or an.get("marca"),
                        "qtd_kit_detectada": an.get("qtd_kit_detectada") or an.get("qtd_kit"),
                        "cores_encontradas": an.get("cores_encontradas")
                        or an.get("cores_detectadas")
                        or [],
                    }
                )
    if isinstance(kits, dict):
        cons_k = kits.get("consolidado") if isinstance(kits.get("consolidado"), dict) else kits
        bruto.extend(cons_k.get("top_vendas") or cons_k.get("top_anuncios") or [])
    vistos: set[str] = set()
    unicos: list[dict[str, Any]] = []
    for an in bruto:
        if not isinstance(an, dict):
            continue
        titulo = str(an.get("titulo") or "").strip()
        if not titulo:
            continue
        chave = str(an.get("item_id") or titulo)
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(an)
    return unicos


def cruzar_marca_kit_de_snapshots(
    *,
    mercado: dict[str, Any] | None = None,
    anita: dict[str, Any] | None = None,
    kits: dict[str, Any] | None = None,
    tendencias: dict[str, Any] | list | None = None,
) -> list[dict[str, Any]]:
    """Cruza snapshots (sem nova busca ML)."""
    anuncios = anuncios_de_snapshots(mercado=mercado, anita=anita, kits=kits)
    if isinstance(tendencias, list):
        tend_list = [t for t in tendencias if isinstance(t, dict)]
    else:
        tend_list = tendencias_de_snapshot(tendencias if isinstance(tendencias, dict) else None)
    return cruzar_marca_kit_tendencia(anuncios, tend_list)


def persistir_ranking_marca_kit(itens: list[dict[str, Any]]) -> None:
    from datetime import datetime, timezone

    from core.atomic_io import escrever_json_atomico
    from core.config import ROOT

    boas = [i for i in itens if i.get("performance_boa")]
    escrever_json_atomico(
        ROOT / "logs" / "esmaltes_marca_kit_ultima.json",
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": len(itens),
            "boas_performance": len(boas),
            "ranking": itens[:20],
            "marca_kit_boas": boas[:8],
        },
    )


def emitir_metricas_marca_kit(itens: list[dict[str, Any]]) -> None:
    from core.datadog_metrics import gauge

    boas = [i for i in itens if i.get("performance_boa")]
    gauge("esmaltes.marca_kit.total", float(len(itens)))
    gauge("esmaltes.marca_kit.boas_performance", float(len(boas)))
    for row in itens[:12]:
        tags = [f"marca:{row.get('slug') or 'indefinida'}", f"kit:{int(row.get('qtd_kit') or 0)}"]
        gauge("esmaltes.marca_kit.score", float(row.get("score") or 0), tags=tags)
        gauge("esmaltes.marca_kit.vendidos", float(row.get("vendidos") or 0), tags=tags)
        gauge(
            "esmaltes.marca_kit.performance_boa",
            1.0 if row.get("performance_boa") else 0.0,
            tags=tags,
        )
    persistir_ranking_marca_kit(itens)


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
    marca_kit = cruzar_marca_kit_tendencia(classificados, tendencias)

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
        "oportunidades_marca_kit": marca_kit[:8],
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
    marca_kit = _fundir_marca_kit(
        [list(r.get("oportunidades_marca_kit") or []) for r in ok]
    )

    return {
        "segmentos_varridos": len(ok),
        "total_web_hits": total_web,
        "total_anuncios_mp": total_mp,
        "top_oportunidades": oportunidades[:12],
        "top_confirmadas": confirmadas[:10],
        "saturadas_mp": saturadas[:8],
        "top_termos_web": [{"termo": t, "mencoes": n} for t, n in top_termos_web],
        "todas_tendencias": todas_tendencias[:40],
        "top_marca_kit": marca_kit[:12],
        "marca_kit_boas": [x for x in marca_kit if x.get("performance_boa")][:8],
    }
