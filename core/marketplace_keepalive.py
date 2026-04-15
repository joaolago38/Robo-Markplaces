"""
core/marketplace_keepalive.py
Registra último acesso bem-sucedido por marketplace.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
STATE_FILE = ROOT / "logs" / "marketplace_keepalive.json"


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def registrar_acesso(nome_marketplace: str) -> None:
    state = _load_state()
    state[nome_marketplace] = datetime.now(timezone.utc).isoformat()
    _save_state(state)


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
