"""
Heartbeat de integridade ML + gauges de catálogo (frente_publicada / dados_api_ok)
e Product Ads do dia (ads_gatilho fica fora do ciclo 30 min).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("agente_observabilidade_ml")


def executar(*, anuncios: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Audita espelho ML, emite catálogo Impala. Nunca lança."""
    saida: dict[str, Any] = {"ok": False}
    try:
        from integracoes.ml.integridade_dados_ml import executar as auditar_ml

        saida["integridade"] = auditar_ml(anuncios=anuncios)
        saida["ok"] = True
    except Exception as exc:
        logger.warning("observabilidade integridade: %s", exc)
        saida["erro_integridade"] = str(exc)
    try:
        from integracoes.esmaltes.metricas_catalogo_impala import emitir_metricas_catalogo_impala

        saida["catalogo"] = emitir_metricas_catalogo_impala()
    except Exception as exc:
        logger.warning("observabilidade catalogo: %s", exc)
        saida["erro_catalogo"] = str(exc)
    try:
        from integracoes.ml.ml_product_ads import (
            emitir_metricas_ads_hoje,
            listar_campanhas,
            ultima_listagem_ok,
        )

        campanhas_dia = listar_campanhas(dias=1, emitir_visibilidade=False)
        emitir_metricas_ads_hoje(campanhas_dia, fonte_ok=ultima_listagem_ok())
        saida["ads_hoje"] = {
            "ok": ultima_listagem_ok(),
            "campanhas": len(campanhas_dia),
        }
    except Exception as exc:
        logger.warning("observabilidade ads hoje: %s", exc)
        saida["erro_ads_hoje"] = str(exc)
        try:
            from integracoes.ml.ml_product_ads import emitir_metricas_ads_hoje

            emitir_metricas_ads_hoje([], fonte_ok=False)
        except Exception:
            pass
    return saida
