"""
agentes/ml/agente_resumo_conta_ml.py
Espelho do Resumo do vendedor ML → Telegram gestor.

Uso:
  python -m agentes.ml.agente_resumo_conta_ml
  python -m agentes.ml.agente_resumo_conta_ml --sem-alerta
  python -m agentes.ml.agente_resumo_conta_ml --forcar
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import (
    RESUMO_CONTA_ML_ALERTA,
    RESUMO_CONTA_ML_COOLDOWN_SEG,
    RESUMO_CONTA_ML_MAX_PERFORMANCE,
    ROOT,
)
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.ml.resumo_conta import (
    coletar_resumo_conta,
    emitir_metricas_saude_conta,
    montar_mensagem_telegram,
)

logger = logging.getLogger("agente_resumo_conta_ml")

SNAPSHOT_PATH = ROOT / "logs" / "resumo_conta_ml_ultima.json"


def executar(*, enviar_alerta: bool = True, forcar: bool = False) -> dict[str, Any]:
    """Coleta resumo da conta e opcionalmente envia ao Telegram. Nunca lança."""
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — resumo conta sem envio")

        resumo = coletar_resumo_conta(max_anuncios_performance=RESUMO_CONTA_ML_MAX_PERFORMANCE)
        emitir_metricas_saude_conta(resumo)
        msg = montar_mensagem_telegram(resumo)
        escrever_json_atomico(
            SNAPSHOT_PATH,
            {
                **resumo,
                "mensagem": msg,
            },
        )

        enviado = False
        if enviar_alerta and RESUMO_CONTA_ML_ALERTA and resumo.get("ok") and msg:
            chave = "ml:resumo_conta:forcar" if forcar else chave_resumo_periodo(
                "ml:resumo_conta", horas_por_bucket=20
            )
            cooldown = 0 if forcar else RESUMO_CONTA_ML_COOLDOWN_SEG
            enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave,
                    cooldown_segundos=cooldown,
                    agente_id="resumo_conta_ml",
                    _ignorar_cooldown=forcar,
                )
            )
            if enviado:
                incrementar("ml.resumo_conta.telegram_ok")
            else:
                incrementar("ml.resumo_conta.telegram_skip")

        if resumo.get("ok"):
            incrementar("ml.resumo_conta.ok")
        else:
            incrementar("ml.resumo_conta.erro")

        return {
            "ok": bool(resumo.get("ok")),
            "erro": resumo.get("erro"),
            "alerta_enviado": enviado,
            "anuncios_ativos": resumo.get("anuncios_ativos"),
            "anuncios_a_melhorar": resumo.get("anuncios_a_melhorar_total"),
            "perguntas": resumo.get("perguntas_pendentes"),
            "mensagem": msg,
        }
        except Exception as exc:
            logger.error("agente_resumo_conta_ml erro: %s", exc)
            incrementar("ml.resumo_conta.erro")
            try:
                emitir_metricas_saude_conta({"ok": False})
            except Exception:
                pass
            return {"ok": False, "erro": str(exc), "alerta_enviado": False}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Resumo conta ML → Telegram")
    parser.add_argument("--sem-alerta", action="store_true")
    parser.add_argument("--forcar", action="store_true", help="Ignora cooldown do Telegram")
    args = parser.parse_args()
    out = executar(enviar_alerta=not args.sem_alerta, forcar=args.forcar)
    resumo_print = {
        "ok": out.get("ok"),
        "erro": out.get("erro"),
        "alerta_enviado": out.get("alerta_enviado"),
        "anuncios_ativos": out.get("anuncios_ativos"),
        "anuncios_a_melhorar": out.get("anuncios_a_melhorar"),
        "perguntas": out.get("perguntas"),
    }
    print(resumo_print)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
