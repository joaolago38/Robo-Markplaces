"""
Agrega pedidos reais em dia (calendário BRT), 7d e 30d e emite gauges Datadog.

CNPJ Impala = conta marketplace conectada hoje.
CNPJ Masterprint = só quando houver pedidos próprios (sem inventar seller).
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from core.datadog_metrics import gauge
from core.horario import TZ_BRASIL, agora_brasil
from integracoes.esmaltes.metricas_catalogo_impala import kit_tag

logger = logging.getLogger("metricas_periodo_cnpj")

_JANELAS = ("dia", "semana", "mes")
_TOP_N = 10
_RE_PROD = re.compile(r"[^a-z0-9]+")

CNPJ_IMPALA = "impala"
CNPJ_MASTERPRINT = "masterprint"


def prod_tag(sku: str) -> str:
    """Tag de produto sem prefixo sku: (bloqueado no Datadog)."""
    compact = _RE_PROD.sub("", str(sku or "").strip().lower())
    return f"prod:{(compact or 'x')[:24]}"


def _parse_dt(valor: Any) -> datetime | None:
    raw = str(valor or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_BRASIL)


def _flatten(pedidos_por_mp: dict[str, list[dict[str, Any]]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lista in (pedidos_por_mp or {}).values():
        if not isinstance(lista, list):
            continue
        for ped in lista:
            if isinstance(ped, dict):
                out.append(ped)
    return out


def _em_janela(dt: datetime, janela: str, agora: datetime) -> bool:
    if janela == "dia":
        return dt.date() == agora.date()
    if janela == "semana":
        return dt >= agora - timedelta(days=7)
    return dt >= agora - timedelta(days=30)


def agregar_periodo(
    pedidos: list[dict[str, Any]],
    *,
    agora: datetime | None = None,
    tag_produto: str = "kit",
) -> dict[str, Any]:
    """Totais e ranking por janela. ranking usa tag kit: (Impala) ou prod:."""
    agora = agora or agora_brasil()
    totais: dict[str, dict[str, float]] = {
        j: {"receita": 0.0, "unidades": 0.0, "pedidos": 0.0} for j in _JANELAS
    }
    por_prod: dict[str, dict[str, dict[str, float]]] = {
        j: defaultdict(lambda: {"receita": 0.0, "unidades": 0.0}) for j in _JANELAS
    }
    vistos: dict[str, set[str]] = {j: set() for j in _JANELAS}
    sem_data = 0

    for ped in pedidos:
        dt = _parse_dt(ped.get("data") or ped.get("date_created"))
        if dt is None:
            sem_data += 1
            continue
        oid = str(ped.get("order_id") or ped.get("id") or "")
        itens = ped.get("itens") if isinstance(ped.get("itens"), list) else []
        for janela in _JANELAS:
            if not _em_janela(dt, janela, agora):
                continue
            if oid and oid not in vistos[janela]:
                vistos[janela].add(oid)
                totais[janela]["pedidos"] += 1
            for item in itens:
                if not isinstance(item, dict):
                    continue
                sku = str(item.get("sku") or "").strip()
                try:
                    qtd = float(item.get("quantidade") or 0)
                except (TypeError, ValueError):
                    qtd = 0.0
                try:
                    unit = float(item.get("preco_unitario") or 0)
                except (TypeError, ValueError):
                    unit = 0.0
                rec = unit * qtd
                totais[janela]["receita"] += rec
                totais[janela]["unidades"] += qtd
                if tag_produto == "prod":
                    chave = prod_tag(sku)
                else:
                    chave = kit_tag(sku)
                por_prod[janela][chave]["receita"] += rec
                por_prod[janela][chave]["unidades"] += qtd

    ranking: dict[str, list[tuple[str, float, float]]] = {}
    for janela in _JANELAS:
        itens_r = [
            (tag, vals["unidades"], vals["receita"])
            for tag, vals in por_prod[janela].items()
        ]
        itens_r.sort(key=lambda x: (x[1], x[2]), reverse=True)
        ranking[janela] = itens_r[:_TOP_N]
    return {"totais": totais, "ranking": ranking, "sem_data": float(sem_data)}


def pedidos_e_fonte_impala(
    pedidos_por_mp: dict[str, list[dict[str, Any]]] | None,
    ok_map: dict[str, bool] | None,
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    """Só Mercado Livre. Flatten de Shopee/Magalu no CNPJ Impala seria ponto cego."""
    ok = bool((ok_map or {}).get("mercadolivre"))
    lista = (pedidos_por_mp or {}).get("mercadolivre") or []
    return {"mercadolivre": lista if ok else []}, ok


def emitir_periodo_cnpj(
    cnpj: str,
    pedidos_por_mp: dict[str, list[dict[str, Any]]] | None,
    *,
    fonte_ok: bool,
    tag_produto: str = "kit",
) -> dict[str, Any]:
    """Gauges `vendas.periodo.*` com tags cnpj + janela. Nunca lança."""
    slug = (cnpj or "").strip().lower() or "x"
    base = [f"cnpj:{slug}"]
    try:
        gauge("vendas.periodo.fonte_ok", 1.0 if fonte_ok else 0.0, tags=base)
        gauge(
            "vendas.periodo.token_ausente",
            1.0 if (slug == CNPJ_MASTERPRINT and not fonte_ok) else 0.0,
            tags=base,
        )
        if not fonte_ok:
            gauge("vendas.periodo.sem_data", 0.0, tags=base)
            for janela in _JANELAS:
                tags = [*base, f"janela:{janela}"]
                gauge("vendas.periodo.receita", 0.0, tags=tags)
                gauge("vendas.periodo.unidades", 0.0, tags=tags)
                gauge("vendas.periodo.pedidos", 0.0, tags=tags)
                gauge("vendas.periodo.rank_n", 0.0, tags=tags)
            return {"cnpj": slug, "fonte_ok": False, "totais": {}, "sem_data": 0}

        agg = agregar_periodo(_flatten(pedidos_por_mp), tag_produto=tag_produto)
        gauge("vendas.periodo.sem_data", float(agg.get("sem_data") or 0), tags=base)
        for janela in _JANELAS:
            tags = [*base, f"janela:{janela}"]
            tot = agg["totais"][janela]
            gauge("vendas.periodo.receita", round(tot["receita"], 2), tags=tags)
            gauge("vendas.periodo.unidades", round(tot["unidades"], 2), tags=tags)
            gauge("vendas.periodo.pedidos", float(tot["pedidos"]), tags=tags)
            rank = agg["ranking"][janela]
            gauge("vendas.periodo.rank_n", float(len(rank)), tags=tags)
            for chave, unid, rec in rank:
                ptags = [*tags, chave]
                gauge("vendas.periodo.ranking_unidades", round(unid, 2), tags=ptags)
                gauge("vendas.periodo.ranking_receita", round(rec, 2), tags=ptags)
        return {"cnpj": slug, "fonte_ok": True, **agg}
    except Exception as exc:
        logger.debug("emitir_periodo_cnpj %s: %s", slug, exc)
        return {"cnpj": slug, "fonte_ok": False, "erro": str(exc)[:160]}
