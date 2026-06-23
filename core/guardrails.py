"""
core/guardrails.py
Kill switch global e helpers de bloqueio de escrita real.
"""
from __future__ import annotations

from core import config

MSG_BLOQUEIO_ESCRITA_GLOBAL = (
    "ROBO_PAUSAR_ESCRITA ativo — toda escrita real está bloqueada globalmente"
)


def bloqueio_escrita_global() -> dict | None:
    """Retorna dict de erro padronizado se o kill switch global estiver ativo; None se a escrita pode seguir."""
    if config.ROBO_PAUSAR_ESCRITA:
        return {"ok": False, "erro": MSG_BLOQUEIO_ESCRITA_GLOBAL}
    return None


def alertar_bloqueio_escrita_global() -> None:
    try:
        from core.notificador import alertar_gestor

        alertar_gestor(f"⚠️ {MSG_BLOQUEIO_ESCRITA_GLOBAL}")
    except Exception:
        pass
