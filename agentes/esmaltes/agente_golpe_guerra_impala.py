"""
agentes/esmaltes/agente_golpe_guerra_impala.py
Telegram só quando a doutrina classifica um golpe (não IGNORAR).

Uso:
  python -m agentes.esmaltes.agente_golpe_guerra_impala
  python -m agentes.esmaltes.agente_golpe_guerra_impala --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

from core.config import (
    GOLPE_GUERRA_IMPALA_ALERTA,
    GOLPE_GUERRA_IMPALA_ATIVO,
    GOLPE_GUERRA_IMPALA_COOLDOWN_SEG,
)
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor, gestor_telegram_configurado
from core.prontidao import pode_alertar_esmaltes
from integracoes.esmaltes.golpe_guerra_impala import processar_de_snapshot_batalha

logger = logging.getLogger("agente_golpe_guerra_impala")


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    """Lê snapshot da batalha, classifica o golpe, alerta se disparar. Nunca lança."""
    try:
        if not GOLPE_GUERRA_IMPALA_ATIVO:
            return {"ok": False, "motivo": "agente_desligado", "disparar": False}

        out = processar_de_snapshot_batalha()
        disparar = bool(out.get("disparar"))
        enviado = False
        if enviar_alerta and disparar and GOLPE_GUERRA_IMPALA_ALERTA:
            pode, motivo = pode_alertar_esmaltes()
            if not pode:
                logger.warning("Telegram esmaltes bloqueado: %s", motivo)
            elif not gestor_telegram_configurado():
                logger.warning("Telegram gestor não configurado")
            else:
                golpe = out.get("golpe") if isinstance(out.get("golpe"), dict) else {}
                sku = str(golpe.get("sku") or "x")
                classif = str(golpe.get("classificacao") or "x")
                enviado = bool(
                    alertar_gestor(
                        out.get("mensagem") or "",
                        chave=f"golpe_guerra:{sku}:{classif}",
                        cooldown_segundos=GOLPE_GUERRA_IMPALA_COOLDOWN_SEG,
                        agente_id="golpe_guerra_impala",
                    )
                )
        out["alerta_enviado"] = enviado
        incrementar("golpe_guerra_impala.ok")
        return out
    except Exception as exc:
        logger.error("agente_golpe_guerra_impala: %s", exc)
        incrementar("golpe_guerra_impala.erro")
        return {"ok": False, "erro": str(exc), "disparar": False, "alerta_enviado": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Golpe da guerra Impala")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args()
    print(executar(enviar_alerta=not args.sem_alerta))
