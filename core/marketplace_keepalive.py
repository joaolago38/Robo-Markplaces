"""
core/marketplace_keepalive.py
Registra último acesso bem-sucedido por marketplace.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.atomic_io import ler_e_atualizar_json, ler_json

ROOT = Path(__file__).parent.parent
STATE_FILE = ROOT / "logs" / "marketplace_keepalive.json"


def _load_state() -> dict:
    return ler_json(STATE_FILE, default={})


def registrar_acesso(nome_marketplace: str) -> None:
    def _atualizar(state: dict) -> dict:
        state = dict(state or {})
        state[nome_marketplace] = datetime.now(timezone.utc).isoformat()
        return state

    # Lê + atualiza + grava sob um único lock — evita que duas
    # execuções concorrentes (ex.: API viva + um workflow agendado)
    # leiam o mesmo estado antigo e uma sobrescreva o registro da outra.
    ler_e_atualizar_json(STATE_FILE, _atualizar, default={})


def dias_sem_acesso(nome_marketplace: str) -> int | None:
    state = _load_state()
    raw = state.get(nome_marketplace)
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - ts).days
