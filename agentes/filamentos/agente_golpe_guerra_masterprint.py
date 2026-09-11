"""
agentes/filamentos/agente_golpe_guerra_masterprint.py
Telegram só quando a doutrina classifica um golpe (não IGNORAR).

Uso:
  python -m agentes.filamentos.agente_golpe_guerra_masterprint
  python -m agentes.filamentos.agente_golpe_guerra_masterprint --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

from core.config import (
    GOLPE_GUERRA_MASTERPRINT_ALERTA,
    GOLPE_GUERRA_MASTERPRINT_ATIVO,
)
from core.datadog_metrics import incrementar
from integracoes.filamentos.golpe_guerra_masterprint import processar_de_snapshot_batalha

logger = logging.getLogger("agente_golpe_guerra_masterprint")


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if not GOLPE_GUERRA_MASTERPRINT_ATIVO:
            return {"ok": False, "motivo": "agente_desligado", "disparar": False}

        out = processar_de_snapshot_batalha()
        if not enviar_alerta or not GOLPE_GUERRA_MASTERPRINT_ALERTA:
            out["alerta_enviado"] = False
        incrementar("golpe_guerra_masterprint.ok")
        return out
    except Exception as exc:
        logger.error("agente_golpe_guerra_masterprint: %s", exc)
        incrementar("golpe_guerra_masterprint.erro")
        return {"ok": False, "erro": str(exc), "disparar": False, "alerta_enviado": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Golpe da guerra PETG Masterprint")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args()
    print(executar(enviar_alerta=not args.sem_alerta))
