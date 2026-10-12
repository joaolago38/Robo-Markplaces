"""
core/claude_toggle.py
Toggle mestre para ligar/desligar chamadas Claude sem remover a API key.

Prioridade:
  1. Saldo (atualizado_por=saldo) — manda sobre CLAUDE_ATIVO do Actions
     sem crédito → off; crédito detectado → on
  2. Pausa manual no arquivo logs/claude_toggle.json
  3. CLAUDE_ATIVO=0 no .env / vars do Actions (só se o saldo não estiver
     gerindo o toggle)

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
POR_SALDO = "saldo"
MOTIVO_SEM_CREDITO = "sem_credito"
MOTIVO_SALDO_OK = "saldo_ok"
MOTIVO_ECONOMIA_CREDITOS = "economia_creditos"
_MOTIVOS_SALDO = (MOTIVO_SEM_CREDITO, MOTIVO_SALDO_OK, MOTIVO_ECONOMIA_CREDITOS, "economia")


def _cfg_env_ativo() -> bool:
    from core import config as cfg

    return bool(getattr(cfg, "CLAUDE_ATIVO", True))


def _gerido_por_saldo(data: dict[str, Any]) -> bool:
    por = str(data.get("atualizado_por") or "")
    motivo = str(data.get("motivo") or "")
    return por == POR_SALDO or motivo in _MOTIVOS_SALDO


def estado_toggle() -> dict[str, Any]:
    """Estado consolidado do toggle (saldo + arquivo + env)."""
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

    gerido_saldo = arquivo_definido and _gerido_por_saldo(data)
    motivo = ""
    fonte = "ligado"
    if gerido_saldo:
        # Crédito manda: Actions (CLAUDE_ATIVO) não liga nem desliga.
        ativo = arquivo_ok
        if not ativo:
            motivo = str(data.get("motivo") or MOTIVO_SEM_CREDITO)
            fonte = "saldo"
        else:
            fonte = "saldo"
    else:
        ativo = env_ok and arquivo_ok
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
        "saldo_sondado_em": data.get("saldo_sondado_em") or "",
        "gerido_por_saldo": gerido_saldo,
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


def sem_credito_ativo() -> bool:
    """True se o Claude está desligado porque o saldo acabou (não pausa manual)."""
    st = estado_toggle()
    if st.get("ativo"):
        return False
    return st.get("fonte") == "saldo" or st.get("arquivo_motivo") == MOTIVO_SEM_CREDITO


def definir_ativo(
    ativo: bool,
    *,
    motivo: str = "",
    atualizado_por: str = "manual",
) -> dict[str, Any]:
    """Grava toggle em disco (momentâneo, compartilhado via cache Actions se configurado)."""
    atual = ler_json(TOGGLE_PATH, default={})
    if not isinstance(atual, dict):
        atual = {}
    payload = {
        "ativo": bool(ativo),
        "motivo": (motivo or ("operacao" if ativo else "pausa_manual")).strip()[:200],
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "atualizado_por": (atualizado_por or "manual").strip()[:80],
    }
    if atual.get("saldo_sondado_em"):
        payload["saldo_sondado_em"] = atual["saldo_sondado_em"]
    escrever_json_atomico(TOGGLE_PATH, payload)
    logger.info(
        "Claude toggle → ativo=%s motivo=%s por=%s",
        payload["ativo"],
        payload["motivo"],
        payload["atualizado_por"],
    )
    return estado_toggle()


def registrar_sondagem() -> None:
    """Marca o instante da última sondagem de crédito (cooldown)."""
    data = ler_json(TOGGLE_PATH, default={})
    if not isinstance(data, dict):
        data = {}
    data["saldo_sondado_em"] = datetime.now(timezone.utc).isoformat()
    escrever_json_atomico(TOGGLE_PATH, data)


def inativar_por_saldo(*, motivo: str = MOTIVO_SEM_CREDITO) -> dict[str, Any]:
    """Desliga Claude no código — vale mesmo com CLAUDE_ATIVO=1 no Actions."""
    data = ler_json(TOGGLE_PATH, default={})
    if isinstance(data, dict) and data.get("ativo") is False:
        return estado_toggle()
    st = definir_ativo(False, motivo=motivo or MOTIVO_SEM_CREDITO, atualizado_por=POR_SALDO)
    _emitir_gauge_sem_credito(1.0)
    return st


def reativar_por_saldo() -> dict[str, Any]:
    """Religa Claude quando há crédito. Não desfaz pausa manual."""
    data = ler_json(TOGGLE_PATH, default={})
    if isinstance(data, dict) and data.get("ativo") is False and not _gerido_por_saldo(data):
        logger.info("Claude continua pausado manualmente — saldo não religa")
        return estado_toggle()
    st = definir_ativo(True, motivo=MOTIVO_SALDO_OK, atualizado_por=POR_SALDO)
    _emitir_gauge_sem_credito(0.0)
    return st


def _emitir_gauge_sem_credito(valor: float) -> None:
    try:
        from core.datadog_metrics import gauge

        gauge("claude.sem_credito", float(valor))
    except Exception:
        logger.debug("gauge claude.sem_credito falhou", exc_info=True)
