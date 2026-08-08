"""
integracoes/esmaltes/metricas_catalogo_impala.py
Heartbeat Datadog do catálogo Impala (cores×preço×margem).

Emite gauges agregados + por papel de guerra.
Nunca usa tag sku: (bloqueada em core.datadog_metrics).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from core.config import TAXA_CANAL_PADRAO_PCT
from core.datadog_metrics import gauge, incrementar
from integracoes.esmaltes.crescimento_esmaltes import _mlb_valido

logger = logging.getLogger("metricas_catalogo_impala")

_RE_KIT = re.compile(r"[^a-z0-9]+")


def kit_tag(sku: str) -> str:
    """IMP-PERL-004 → kit:perl004 (baixa cardinalidade, sem prefixo sku:)."""
    s = str(sku or "").strip().upper()
    if s.startswith("IMP-"):
        s = s[4:]
    elif s.startswith("BUNDLE-"):
        s = "b" + s[7:]
    compact = _RE_KIT.sub("", s.lower())
    return f"kit:{(compact or 'x')[:24]}"


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _item_id(produto: dict[str, Any]) -> str:
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    return str(ml.get("item_id") or "").strip()


def _preco_e_taxa(produto: dict[str, Any]) -> tuple[float, float]:
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    preco = _f(ml.get("preco") or produto.get("preco"))
    taxa = _f(ml.get("taxa_canal_pct"), TAXA_CANAL_PADRAO_PCT)
    return preco, taxa


def margem_real_pct(produto: dict[str, Any]) -> float | None:
    preco, taxa = _preco_e_taxa(produto)
    custo = _f(produto.get("custo_total") or produto.get("custo"))
    if preco <= 0 or custo <= 0:
        return None
    liquida = preco * (1 - taxa / 100.0)
    return round(100.0 * (liquida - custo) / preco, 2)


def gap_mercado_pct(produto: dict[str, Any]) -> float | None:
    """% abaixo do preço de mercado (positivo = vendendo mais barato que o ref)."""
    preco, _ = _preco_e_taxa(produto)
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    mercado = _f(produto.get("preco_ml_mercado") or ml.get("preco_concorrente"))
    if mercado <= 0 or preco <= 0:
        return None
    return round(100.0 * (mercado - preco) / mercado, 2)


def _estoque_zero(produto: dict[str, Any]) -> bool:
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    est_ml = ml.get("estoque")
    est_tot = produto.get("estoque_total")
    try:
        if est_tot is not None and int(est_tot) == 0:
            if est_ml is None or int(est_ml) == 0:
                return True
    except (TypeError, ValueError):
        pass
    try:
        if est_ml is not None and int(est_ml) == 0 and (
            est_tot is None or int(est_tot) == 0
        ):
            return True
    except (TypeError, ValueError):
        pass
    return False


def montar_snapshot_catalogo(
    *,
    produtos: list[dict[str, Any]],
    guerra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Calcula contadores e séries por kit sem enviar ao Datadog."""
    guerra = guerra or []
    papel_por_sku = {
        str(g.get("sku") or "").strip().upper(): str(g.get("papel") or "guerra").strip().lower()
        for g in guerra
        if str(g.get("sku") or "").strip()
    }
    skus_guerra = set(papel_por_sku)

    kits: list[dict[str, Any]] = []
    p0 = p1 = sem_mlb = estoque_z = 0
    guerra_sem_mlb = guerra_estoque_z = 0

    for p in produtos:
        if not isinstance(p, dict):
            continue
        sku = str(p.get("sku") or "").strip()
        if not sku:
            continue
        sku_u = sku.upper()
        prio = str(p.get("prioridade") or "P?").strip().upper() or "P?"
        if prio == "P0":
            p0 += 1
        elif prio == "P1":
            p1 += 1

        mlb_ok = _mlb_valido(_item_id(p))
        if not mlb_ok:
            sem_mlb += 1
        ez = _estoque_zero(p)
        if ez:
            estoque_z += 1

        papel = papel_por_sku.get(sku_u, "catalogo")
        if sku_u in skus_guerra:
            if not mlb_ok:
                guerra_sem_mlb += 1
            if ez:
                guerra_estoque_z += 1

        kits.append(
            {
                "sku": sku_u,
                "papel": papel,
                "prio": prio.lower(),
                "kit_tag": kit_tag(sku_u),
                "guerra": sku_u in skus_guerra,
                "mlb_ok": mlb_ok,
                "estoque_zero": ez,
                "score": _f(p.get("score_alavancagem")),
                "vd_dia_ref": _f(p.get("vd_dia_ml_ref")),
                "margem_trabalho_pct": _f(p.get("margem_trabalho_pct")),
                "margem_real_pct": margem_real_pct(p),
                "gap_mercado_pct": gap_mercado_pct(p),
                "custo_total": _f(p.get("custo_total") or p.get("custo")),
                "preco": _preco_e_taxa(p)[0],
                "taxa_canal_pct": _preco_e_taxa(p)[1],
                "preco_ml_mercado": _f(p.get("preco_ml_mercado")),
                "fase": _f(p.get("fase_atual"), 1.0),
                "lucro_ref_ml": _f(p.get("lucro_ref_ml")),
                "invest_validacao_reais": (
                    _f(p["invest_validacao_reais"])
                    if p.get("invest_validacao_reais") is not None
                    else None
                ),
                "frete_estimado": _f(p.get("frete_estimado")),
            }
        )

    custo_investido = round(sum(float(k["custo_total"] or 0) for k in kits), 2)
    return {
        "kits_total": len(kits),
        "kits_p0": p0,
        "kits_p1": p1,
        "sem_mlb": sem_mlb,
        "estoque_zero": estoque_z,
        "guerra_total": len(skus_guerra),
        "guerra_sem_mlb": guerra_sem_mlb,
        "guerra_estoque_zero": guerra_estoque_z,
        "custo_investido": custo_investido,
        "kits": kits,
    }


def emitir_metricas_catalogo_impala(
    *,
    produtos: list[dict[str, Any]] | None = None,
    guerra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Carrega catálogo/guerra se não passados e envia gauges.
    Nunca lança.
    """
    try:
        if produtos is None:
            from core.catalogo_produtos import carregar_produtos_catalogo

            produtos = carregar_produtos_catalogo()
        if guerra is None:
            from integracoes.esmaltes.decisao_dia_esmaltes import carregar_skus_guerra

            guerra = carregar_skus_guerra()

        snap = montar_snapshot_catalogo(produtos=produtos or [], guerra=guerra or [])

        gauge("catalogo.kits_total", float(snap["kits_total"]))
        gauge("catalogo.kits_p0", float(snap["kits_p0"]))
        gauge("catalogo.kits_p1", float(snap["kits_p1"]))
        gauge("catalogo.sem_mlb", float(snap["sem_mlb"]))
        gauge("catalogo.estoque_zero", float(snap["estoque_zero"]))
        gauge("catalogo.guerra_total", float(snap["guerra_total"]))
        gauge("catalogo.guerra_sem_mlb", float(snap["guerra_sem_mlb"]))
        gauge("catalogo.guerra_estoque_zero", float(snap["guerra_estoque_zero"]))
        # Soma dos custos unitários do catálogo (= capital de custo / investido em produto)
        gauge("catalogo.custo_investido", float(snap.get("custo_investido") or 0))

        for k in snap["kits"]:
            tags = [
                f"papel:{k['papel']}",
                f"prio:{k['prio']}",
                k["kit_tag"],
                f"guerra:{str(bool(k['guerra'])).lower()}",
            ]
            gauge("catalogo.score", float(k["score"]), tags=tags)
            gauge("catalogo.vd_dia_ref", float(k["vd_dia_ref"]), tags=tags)
            gauge("catalogo.margem_trabalho_pct", float(k["margem_trabalho_pct"]), tags=tags)
            gauge("catalogo.custo_total", float(k["custo_total"]), tags=tags)
            gauge("catalogo.preco", float(k["preco"]), tags=tags)
            gauge("catalogo.taxa_canal_pct", float(k.get("taxa_canal_pct") or 0), tags=tags)
            gauge("catalogo.preco_ml_mercado", float(k["preco_ml_mercado"]), tags=tags)
            gauge("catalogo.fase", float(k["fase"]), tags=tags)
            gauge("catalogo.lucro_ref_ml", float(k["lucro_ref_ml"]), tags=tags)
            gauge("catalogo.mlb_ok", 1.0 if k["mlb_ok"] else 0.0, tags=tags)
            if k.get("invest_validacao_reais") is not None:
                gauge(
                    "catalogo.invest_validacao",
                    float(k["invest_validacao_reais"] or 0),
                    tags=tags,
                )
            if k.get("frete_estimado") is not None:
                gauge("catalogo.frete_estimado", float(k["frete_estimado"] or 0), tags=tags)
            if k["margem_real_pct"] is not None:
                gauge("catalogo.margem_real_pct", float(k["margem_real_pct"]), tags=tags)
            if k["gap_mercado_pct"] is not None:
                gauge("catalogo.gap_mercado_pct", float(k["gap_mercado_pct"]), tags=tags)

        incrementar("catalogo.heartbeat")
        return {"ok": True, **{kk: snap[kk] for kk in snap if kk != "kits"}, "kits_emitidos": len(snap["kits"])}
    except Exception as exc:
        logger.warning("emitir_metricas_catalogo_impala: %s", exc)
        incrementar("catalogo.heartbeat_erro")
        return {"ok": False, "erro": str(exc)}
