"""
Heartbeat de integridade ML + gauges de catálogo (frente_publicada / dados_api_ok).

Roda no orquestrador 30 min para o Vigia não marcar `integridade_ml` como
inativo só porque o monitor_ml (2h) perdeu a corrida do cache Actions.
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
    return saida
