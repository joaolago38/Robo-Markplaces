"""
agentes/esmaltes/agente_visao_atuacao_impala.py
Telegram da visão de atuação: margem operacional, extras dos rivais, link Datadog.

  python -m agentes.esmaltes.agente_visao_atuacao_impala
  python -m agentes.esmaltes.agente_visao_atuacao_impala --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

from core.datadog_metrics import incrementar
from integracoes.esmaltes.radar_diferencial_impala import processar_radar, snapshot_fresco

logger = logging.getLogger("agente_visao_atuacao_impala")


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        fresco = snapshot_fresco(25.0)
        if fresco:
            logger.info("visao atuacao: snapshot fresco — nao sobrescreve amostra ao vivo")
            if enviar_alerta and not fresco.get("alerta_enviado"):
                from integracoes.esmaltes.radar_diferencial_impala import _alertar

                enviado, motivo = _alertar(fresco)
                fresco = {**fresco, "alerta_enviado": enviado, "alerta_motivo": motivo}
            incrementar("visao_atuacao_impala.ok")
            return fresco
        out = processar_radar(enviar_alerta=enviar_alerta)
        incrementar("visao_atuacao_impala.ok")
        return out
    except Exception as exc:
        logger.error("agente_visao_atuacao_impala: %s", exc)
        incrementar("visao_atuacao_impala.erro")
        return {"ok": False, "erro": str(exc), "alerta_enviado": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args()
    msg = executar(enviar_alerta=not args.sem_alerta).get("mensagem") or ""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))
