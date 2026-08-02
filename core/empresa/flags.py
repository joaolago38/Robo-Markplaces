"""core/empresa/flags.py — lê flags do Facade (DIP + patches de teste)."""
from __future__ import annotations

from typing import Any


def flag(nome: str, default: Any = None) -> Any:
    """Lê atributo de core.empresa_contexto; fallback para config."""
    try:
        import core.empresa_contexto as facade

        if hasattr(facade, nome):
            return getattr(facade, nome)
    except Exception:
        pass
    try:
        import core.config as cfg

        return getattr(cfg, nome, default)
    except Exception:
        return default
