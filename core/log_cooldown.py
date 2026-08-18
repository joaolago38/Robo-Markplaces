"""
core/log_cooldown.py
Evita spam no Datadog (handler só envia INFO+) quando o mesmo aviso
se repete a cada job do GitHub Actions (processo novo).

O primeiro emit sobe no nível pedido; os seguintes no intervalo vão
para DEBUG (console/Actions, fora do intake).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from core.config import ROOT

_PATH_PADRAO = ROOT / "logs" / "datadog_log_cooldown.json"
_PATH = _PATH_PADRAO
_ultimo_em_memoria: dict[str, float] = {}


def reset_para_teste(caminho: Path | None = None) -> None:
    """Limpa memória. Com `caminho`, usa esse JSON; sem, volta ao padrão."""
    global _PATH
    _ultimo_em_memoria.clear()
    _PATH = Path(caminho) if caminho is not None else _PATH_PADRAO


def _carregar() -> dict[str, Any]:
    try:
        from core.atomic_io import ler_json

        data = ler_json(_PATH, default={})
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _salvar(estado: dict[str, Any]) -> None:
    try:
        from core.atomic_io import escrever_json_atomico

        escrever_json_atomico(_PATH, estado)
    except Exception:
        pass


def _ultimo_ts(chave: str) -> float:
    mem = float(_ultimo_em_memoria.get(chave) or 0)
    if mem:
        return mem
    estado = _carregar()
    entrada = estado.get(chave)
    if isinstance(entrada, dict):
        ts = float(entrada.get("ts") or 0)
    else:
        try:
            ts = float(entrada or 0)
        except (TypeError, ValueError):
            ts = 0.0
    if ts:
        _ultimo_em_memoria[chave] = ts
    return ts


def _marcar(chave: str, agora: float) -> None:
    _ultimo_em_memoria[chave] = agora
    estado = _carregar()
    estado[chave] = {"ts": agora}
    _salvar(estado)


def log_com_cooldown(
    logger: logging.Logger,
    chave: str,
    msg: str,
    *args: Any,
    nivel: int = logging.WARNING,
    cooldown_segundos: int = 3600,
    **kwargs: Any,
) -> bool:
    """
    Emite `msg` no `nivel` se a chave saiu do cooldown.
    Senão, DEBUG. Retorna True se emitiu no nível pedido.
    """
    agora = time.time()
    ultimo = _ultimo_ts(chave)
    if ultimo and (agora - ultimo) < cooldown_segundos:
        logger.debug(
            "suprimido cooldown %ss chave=%s",
            cooldown_segundos,
            chave,
        )
        return False
    _marcar(chave, agora)
    logger.log(nivel, msg, *args, **kwargs)
    return True
