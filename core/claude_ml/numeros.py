"""core/claude_ml/numeros.py — helpers numéricos (SRP)."""
from __future__ import annotations

from typing import Any


def num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def primeiro_num(*vals: Any, default: float = 0.0) -> float:
    for v in vals:
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return default


def cfg_bool(nome: str, default: bool = True) -> bool:
    from core import config as cfg

    raw = getattr(cfg, nome, default)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ("0", "false", "no", "")
