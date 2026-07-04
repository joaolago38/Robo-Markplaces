"""
agentes/orquestrador/agente_sync_push_main.py
Sync completo após push na branch main — executa todos os agentes sem alterar
os horários (cron) dos workflows existentes.
"""
from __future__ import annotations

import logging

from agentes.orquestrador.agente_orquestrador import executar_ciclo
from agentes.orquestrador.registro_agentes import listar_agentes_push_main
from core.config import PUSH_MAIN_COOLDOWN_RESUMO_SEG

logger = logging.getLogger("agente_sync_push_main")


def executar(*, enviar_resumo_telegram: bool = True) -> dict:
    """
    Roda todos os agentes (30min + extras de deploy). Nunca lança exceção.
    """
    sha = ""
    try:
        import os

        sha = (os.getenv("GITHUB_SHA") or "")[:7]
    except Exception:
        pass
    titulo = "🚀 *Push main — sync completo*"
    if sha:
        titulo = f"{titulo}\n_commit `{sha}`_"

    return executar_ciclo(
        agentes=listar_agentes_push_main(),
        titulo_resumo=titulo,
        chave_cooldown="push:main:sync:resumo",
        cooldown_segundos=PUSH_MAIN_COOLDOWN_RESUMO_SEG,
        prefixo_metrica="push_main",
        enviar_resumo_telegram=enviar_resumo_telegram,
        log_prefix="PushMain",
    )


def main() -> int:
    logger.info("=== Sync push main — todos os agentes ===")
    resultado = executar(enviar_resumo_telegram=True)
    if resultado.get("falhas"):
        logger.warning("Push main: %s agente(s) com falha", resultado["falhas"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
