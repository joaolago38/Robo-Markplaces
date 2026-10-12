"""
integracoes/social/sustentabilidade_ads_ml.py
Cruza gasto Meta Ads (Instagram/Facebook) com vendas reais do Mercado Livre
para avaliar se a conversão/pago está sustentável.

ROAS Meta (pixel) ≠ ROAS real (receita ML / gasto Ads).
"""
from __future__ import annotations

import logging
from typing import Any

from core.config import META_ROAS_MINIMO_MANICURES

logger = logging.getLogger("sustentabilidade_ads_ml")


def _roas(receita: float, gasto: float) -> float:
    if gasto <= 0:
        return 0.0 if receita <= 0 else 999.0
    return round(receita / gasto, 2)


def avaliar_sustentabilidade(
    *,
    gasto_meta: float,
    receita_meta_pixel: float,
    receita_ml: float,
    pedidos_ml: int,
    periodo_dias: int = 1,
    roas_min_real: float | None = None,
    gasto_minimo_avaliar: float = 20.0,
) -> dict[str, Any]:
    """
    Compara gasto Ads × vendas ML.

    status:
      - sustentavel: ROAS real >= meta e receita_ml >= gasto
      - alerta: gastando sem cobertura confortável
      - critico: gasto > receita ML (ou ROAS real bem abaixo)
      - insuficiente_dados: pouca verba / APIs sem dados
    """
    meta_min = float(roas_min_real if roas_min_real is not None else META_ROAS_MINIMO_MANICURES)
    gasto = float(gasto_meta or 0)
    rec_pixel = float(receita_meta_pixel or 0)
    rec_ml = float(receita_ml or 0)
    roas_pixel = _roas(rec_pixel, gasto)
    roas_real = _roas(rec_ml, gasto)
    cobertura = round(rec_ml - gasto, 2)

    motivos: list[str] = []
    if gasto < gasto_minimo_avaliar and pedidos_ml == 0 and rec_ml <= 0:
        status = "insuficiente_dados"
        motivos.append(
            f"gasto Meta R$ {gasto:.2f} abaixo do mínimo para avaliar (R$ {gasto_minimo_avaliar:.0f})"
        )
    elif gasto >= gasto_minimo_avaliar and rec_ml < gasto:
        status = "critico"
        motivos.append(
            f"gasto Ads (R$ {gasto:.2f}) maior que vendas ML (R$ {rec_ml:.2f}) em {periodo_dias}d"
        )
    elif gasto >= gasto_minimo_avaliar and roas_real < meta_min:
        status = "alerta"
        motivos.append(
            f"ROAS real ML/Ads {roas_real:.2f} < meta {meta_min:.2f}"
        )
    elif gasto >= gasto_minimo_avaliar and roas_pixel >= meta_min and roas_real < roas_pixel * 0.6:
        status = "alerta"
        motivos.append(
            f"pixel ROAS {roas_pixel:.2f} otimista vs ML real {roas_real:.2f} — possível attribution gap"
        )
    else:
        status = "sustentavel"
        if gasto < gasto_minimo_avaliar:
            motivos.append("gasto baixo no período — operação saudável ou Ads pouco ativos")
        else:
            motivos.append(f"ROAS real {roas_real:.2f} cobre o Ads com margem")

    permitido_impulsionar = status in ("sustentavel", "insuficiente_dados")
    recomendacao = {
        "sustentavel": "Manter ou escalar 10% nas campanhas com melhor CTR.",
        "alerta": "Pausar criativos fracos; reforçar oferta ML com link direto; reduzir verba 20%.",
        "critico": "Congelar boost pago/orgânico agressivo até ROAS real >= meta; revisar Funil ML.",
        "insuficiente_dados": "Coletar mais dados (Ads + vendas ML) antes de escalar.",
    }.get(status, "Revisar métricas.")

    return {
        "ok": True,
        "periodo_dias": periodo_dias,
        "gasto_meta": round(gasto, 2),
        "receita_meta_pixel": round(rec_pixel, 2),
        "receita_ml": round(rec_ml, 2),
        "pedidos_ml": int(pedidos_ml or 0),
        "roas_pixel": roas_pixel,
        "roas_real": roas_real,
        "roas_min_meta": meta_min,
        "cobertura_reais": cobertura,
        "status": status,
        "permitido_impulsionar": permitido_impulsionar,
        "motivos": motivos,
        "recomendacao": recomendacao,
    }


def coletar_receita_ml(periodo_dias: int = 1) -> dict[str, Any]:
    """Soma pedidos pagos ML no período. Nunca lança."""
    try:
        from integracoes.ml.ml_client import listar_pedidos_detalhado

        pedidos, ok = listar_pedidos_detalhado(dias=max(1, periodo_dias), max_paginas=8)
        if not ok and not pedidos:
            return {"ok": False, "receita_ml": 0.0, "pedidos_ml": 0, "motivo": "ml_api_falhou"}
        receita = sum(float(p.get("total") or 0) for p in pedidos)
        return {
            "ok": True,
            "receita_ml": round(receita, 2),
            "pedidos_ml": len(pedidos),
            "amostra_ids": [str(p.get("order_id") or "") for p in pedidos[:5]],
        }
    except Exception as exc:
        logger.warning("coletar_receita_ml: %s", exc)
        return {"ok": False, "receita_ml": 0.0, "pedidos_ml": 0, "motivo": str(exc)[:160]}


def coletar_gasto_meta(periodo_dias: int = 1) -> dict[str, Any]:
    """Agrega gasto/receita pixel das campanhas Meta. Nunca lança."""
    try:
        from integracoes.meta.meta_ads_client import (
            listar_metricas_campanhas,
            normalizar_metrica_campanha,
        )

        rows = listar_metricas_campanhas(periodo_dias=periodo_dias, limite=100) or []
        campanhas = [normalizar_metrica_campanha(r) for r in rows if isinstance(r, dict)]
        gasto = sum(float(c.get("gasto") or 0) for c in campanhas)
        receita = sum(float(c.get("receita") or 0) for c in campanhas)
        compras = sum(float(c.get("compras") or 0) for c in campanhas)
        return {
            "ok": True,
            "campanhas": len(campanhas),
            "gasto_meta": round(gasto, 2),
            "receita_meta_pixel": round(receita, 2),
            "compras_pixel": round(compras, 2),
            "roas_pixel": _roas(receita, gasto),
        }
    except Exception as exc:
        logger.warning("coletar_gasto_meta: %s", exc)
        return {
            "ok": False,
            "campanhas": 0,
            "gasto_meta": 0.0,
            "receita_meta_pixel": 0.0,
            "compras_pixel": 0.0,
            "roas_pixel": 0.0,
            "motivo": str(exc)[:160],
        }


def monitorar_venda_sustentavel(
    *,
    periodo_dias: int = 1,
    roas_min_real: float | None = None,
    gasto_minimo_avaliar: float = 20.0,
) -> dict[str, Any]:
    """Pipeline completo Meta spend × ML sales."""
    meta = coletar_gasto_meta(periodo_dias)
    ml = coletar_receita_ml(periodo_dias)
    avaliacao = avaliar_sustentabilidade(
        gasto_meta=float(meta.get("gasto_meta") or 0),
        receita_meta_pixel=float(meta.get("receita_meta_pixel") or 0),
        receita_ml=float(ml.get("receita_ml") or 0),
        pedidos_ml=int(ml.get("pedidos_ml") or 0),
        periodo_dias=periodo_dias,
        roas_min_real=roas_min_real,
        gasto_minimo_avaliar=gasto_minimo_avaliar,
    )
    return {
        "ok": bool(meta.get("ok") or ml.get("ok")),
        "meta": meta,
        "ml": ml,
        "avaliacao": avaliacao,
    }
