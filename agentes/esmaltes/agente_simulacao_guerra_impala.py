"""
agentes/esmaltes/agente_simulacao_guerra_impala.py
Simula a frente com anúncios no ar. Telegram só se SIMULACAO_GUERRA_IMPALA_ALERTA=1.

  python -m agentes.esmaltes.agente_simulacao_guerra_impala
  python -m agentes.esmaltes.agente_simulacao_guerra_impala --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

from core.config import SIMULACAO_GUERRA_IMPALA_ALERTA
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor, gestor_telegram_configurado
from integracoes.esmaltes.simulacao_guerra_impala import formatar_mensagem, rodar_simulacao

logger = logging.getLogger("agente_simulacao_guerra_impala")


def executar(*, enviar_alerta: bool = True, cenario_id: str | None = None) -> dict[str, Any]:
    try:
        out = rodar_simulacao(cenario_id=cenario_id)
        msg = formatar_mensagem(out)
        out["mensagem"] = msg
        enviado = False
        if enviar_alerta and SIMULACAO_GUERRA_IMPALA_ALERTA and out.get("ok"):
            if gestor_telegram_configurado():
                enviado = bool(
                    alertar_gestor(
                        msg,
                        chave="simulacao_guerra_impala:resumo",
                        cooldown_segundos=21600,
                        agente_id="simulacao_guerra_impala",
                    )
                )
        out["alerta_enviado"] = enviado
        incrementar("simulacao_guerra_impala.ok")
        return out
    except Exception as exc:
        logger.error("agente_simulacao_guerra_impala: %s", exc)
        incrementar("simulacao_guerra_impala.erro")
        return {"ok": False, "erro": str(exc), "simulacao": True, "alerta_enviado": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sem-alerta", action="store_true")
    parser.add_argument("--cenario", default="")
    args = parser.parse_args()
    print(executar(enviar_alerta=not args.sem_alerta, cenario_id=args.cenario or None).get("mensagem") or "")
