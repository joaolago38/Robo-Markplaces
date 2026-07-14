"""
core/claude_toggle.py
Toggle mestre para ligar/desligar chamadas Claude sem remover a API key.

Prioridade (primeiro que desliga vence):
  1. CLAUDE_ATIVO=0 no .env / secrets / vars do Actions
  2. Arquivo logs/claude_toggle.json com {"ativo": false}

Uso operacional:
  python scripts/toggle_claude.py off --motivo pausa_manual
  python scripts/toggle_claude.py on
  python scripts/toggle_claude.py status
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT

logger = logging.getLogger("claude_toggle")

TOGGLE_PATH = ROOT / "logs" / "claude_toggle.json"


def _cfg_env_ativo() -> bool:
    from core import config as cfg

    return bool(getattr(cfg, "CLAUDE_ATIVO", True))


def estado_toggle() -> dict[str, Any]:
    """Estado consolidado do toggle (env + arquivo)."""
    env_ok = _cfg_env_ativo()
    data = ler_json(TOGGLE_PATH, default={})
    if not isinstance(data, dict):
        data = {}
    arquivo_ativo = data.get("ativo")
    if arquivo_ativo is None:
        arquivo_ok = True
        arquivo_definido = False
    else:
        arquivo_ok = bool(arquivo_ativo)
        arquivo_definido = True

    ativo = env_ok and arquivo_ok
    motivo = ""
    fonte = "ligado"
    if not env_ok:
        motivo = "CLAUDE_ATIVO=0 (env/secrets)"
        fonte = "env"
    elif arquivo_definido and not arquivo_ok:
        motivo = str(data.get("motivo") or "toggle_arquivo_off")
        fonte = "arquivo"

    return {
        "ativo": ativo,
        "motivo": motivo if not ativo else "",
        "fonte": fonte,
        "env_ok": env_ok,
        "arquivo_ok": arquivo_ok,
        "arquivo_definido": arquivo_definido,
        "arquivo_motivo": data.get("motivo") or "",
        "atualizado_em": data.get("atualizado_em"),
        "atualizado_por": data.get("atualizado_por") or "",
        "path": str(TOGGLE_PATH),
    }


def claude_esta_ativo() -> tuple[bool, str]:
    """
    True se Claude pode chamar a API.
    Retorna (ok, motivo_bloqueio).
    """
    st = estado_toggle()
    if st["ativo"]:
        return True, ""
    return False, st["motivo"] or "claude_desligado"


def definir_ativo(
    ativo: bool,
    *,
    motivo: str = "",
    atualizado_por: str = "manual",
) -> dict[str, Any]:
    """Grava toggle em disco (momentâneo, compartilhado via cache Actions se configurado)."""
    payload = {
        "ativo": bool(ativo),
        "motivo": (motivo or ("operacao" if ativo else "pausa_manual")).strip()[:200],
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "atualizado_por": (atualizado_por or "manual").strip()[:80],
    }
    escrever_json_atomico(TOGGLE_PATH, payload)
    logger.info(
        "Claude toggle → ativo=%s motivo=%s por=%s",
        payload["ativo"],
        payload["motivo"],
        payload["atualizado_por"],
    )
    return estado_toggle()
