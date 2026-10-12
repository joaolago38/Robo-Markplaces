"""
integracoes/esmaltes/metricas_progresso_24m.py
Gauges Datadog do plano 24 meses (teto, não previsão).

Metas: R$ 2.500/mês (ano 1) · R$ 20.000/mês (alvo) · Cruzeiro 12/dia · PETG 6/dia · 20 reviews.
Realizado: lucro da janela de pedidos anualizado × 30, ritmo Cruzeiro, ritmo PETG (funil 7d).
"""
from __future__ import annotations

import logging
from typing import Any

from core.datadog_metrics import gauge

logger = logging.getLogger("metricas_progresso_24m")

META_LUCRO_ANO1_MES = 2500.0
META_LUCRO_ALVO_MES = 20000.0
META_CRUZEIRO_UNID_DIA = 12.0
META_PETG_UNID_DIA = 6.0
META_REVIEWS = 20.0


def classificar_cnpj_sku(sku: str) -> str:
    """IMP/BUNDLE/CRZ = CNPJ Impala; resto (filamento/escritório) = Masterprint."""
    s = str(sku or "").strip().upper()
    if s.startswith(("IMP-", "BUNDLE-", "CRZ-")):
        return "impala"
    return "masterprint"


def emitir_metas_progresso_24m() -> None:
    """Constantes do teto — podem ser reenviadas a cada heartbeat de catálogo."""
    gauge("progresso.meta_lucro_ano1_mes", META_LUCRO_ANO1_MES)
    gauge("progresso.meta_lucro_alvo_mes", META_LUCRO_ALVO_MES)
    gauge("progresso.meta_cruzeiro_unid_dia", META_CRUZEIRO_UNID_DIA)
    gauge("progresso.meta_petg_unid_dia", META_PETG_UNID_DIA)
    gauge("progresso.meta_reviews", META_REVIEWS)


def emitir_realizado_vendas(analise: dict[str, Any], *, dias: int = 2) -> None:
    """Lucro da janela de pedidos → ritmo/mês e unid/dia Cruzeiro. Nunca lança."""
    try:
        emitir_metas_progresso_24m()
        janela = max(int(dias or 1), 1)
        lucro = float(analise.get("lucro_reais") or 0)
        lucro_impala = 0.0
        lucro_mp = 0.0
        qtd_crz = 0.0
        for lin in analise.get("linhas") or []:
            if not isinstance(lin, dict):
                continue
            sku = str(lin.get("sku") or "").strip()
            if not sku:
                continue
            lucro_lin = float(lin.get("lucro_reais") or 0)
            qtd = float(lin.get("quantidade") or 0)
            if sku.upper().startswith("CRZ-"):
                qtd_crz += qtd
            if classificar_cnpj_sku(sku) == "impala":
                lucro_impala += lucro_lin
            else:
                lucro_mp += lucro_lin
        fator_mes = 30.0 / janela
        gauge("progresso.janela_dias", float(janela))
        gauge("progresso.lucro_janela", round(lucro, 2))
        gauge("progresso.lucro_mes_estimado", round(lucro * fator_mes, 2))
        gauge(
            "progresso.lucro_mes_impala",
            round(lucro_impala * fator_mes, 2),
            tags=["marca:impala", "fase:1"],
        )
        gauge(
            "progresso.lucro_mes_masterprint",
            round(lucro_mp * fator_mes, 2),
            tags=["marca:masterprint", "fase:2"],
        )
        gauge("progresso.cruzeiro_unid_dia", round(qtd_crz / janela, 4), tags=["marca:impala", "fase:1"])
    except Exception as exc:
        logger.warning("emitir_realizado_vendas: %s", exc)


def emitir_petg_funil(unidades_7d: float) -> None:
    """Ritmo PETG = unidades do funil próprio nos últimos 7d / 7."""
    try:
        gauge(
            "progresso.petg_unid_dia",
            round(float(unidades_7d or 0) / 7.0, 4),
            tags=["marca:masterprint", "fase:2"],
        )
    except Exception as exc:
        logger.warning("emitir_petg_funil: %s", exc)


def prefixo_emite_petg(prefixo: str) -> bool:
    pref = str(prefixo or "").strip().strip(".").lower()
    return "petg" in pref
