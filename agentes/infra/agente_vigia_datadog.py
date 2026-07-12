"""
agentes/infra/agente_vigia_datadog.py
Vigia erros no Datadog, inatividade e ausência de resposta (2h) — alerta crítico.

Uso:
  python -m agentes.infra.agente_vigia_datadog
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    DATADOG_VIGIA_ALERTA_COOLDOWN_SEG,
    DATADOG_VIGIA_CATALOGO_FONTES,
    DATADOG_VIGIA_FALHAR_PROCESSO,
    DATADOG_VIGIA_LIMITE_HORAS_ERRO,
    DATADOG_VIGIA_LIMITE_HORAS_INATIVIDADE,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_critico, alertar_gestor, gestor_telegram_configurado
from integracoes.datadog.vigia_saude import analisar_saude, carregar_fontes

logger = logging.getLogger("agente_vigia_datadog")

HISTORY_PATH = ROOT / "logs" / "datadog_vigia_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "datadog_vigia_ultima.json"


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — vigia Datadog não alertará")

        fontes = carregar_fontes(DATADOG_VIGIA_CATALOGO_FONTES)
        analise = analisar_saude(
            fontes,
            limite_horas_inatividade=DATADOG_VIGIA_LIMITE_HORAS_INATIVIDADE,
            limite_horas_erro=DATADOG_VIGIA_LIMITE_HORAS_ERRO,
        )

        agora = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "timestamp": agora,
            "ok": analise.get("ok"),
            "tem_critico": analise.get("tem_critico"),
            "total_inatividades": analise.get("total_inatividades"),
            "total_erros": analise.get("total_erros"),
            "inatividades": analise.get("inatividades"),
            "erros": analise.get("erros"),
        }
        escrever_json_atomico(SNAPSHOT_PATH, snapshot)

        historico = ler_json(HISTORY_PATH, default={})
        historico["ultima_varredura"] = agora
        historico["ultimo_ok"] = analise.get("ok")
        historico["ultimo_critico"] = analise.get("tem_critico")
        historico["contagem_inatividades"] = analise.get("total_inatividades")
        historico["contagem_erros"] = analise.get("total_erros")
        escrever_json_atomico(HISTORY_PATH, historico)

        gauge("vigia_datadog.inatividades", float(analise.get("total_inatividades") or 0))
        gauge("vigia_datadog.erros_abertos", float(analise.get("total_erros") or 0))
        gauge("vigia_datadog.saudavel", 1.0 if analise.get("ok") else 0.0)

        alerta_enviado = False
        msg = analise.get("mensagem_critica") or ""
        if enviar_alerta and msg:
            if analise.get("tem_critico"):
                alerta_enviado = bool(
                    alertar_critico(
                        msg,
                        chave="vigia_datadog:critico",
                        cooldown_segundos=DATADOG_VIGIA_ALERTA_COOLDOWN_SEG,
                    )
                )
            else:
                from core.telegram_explicacao import cabecalho_agente

                alerta_enviado = bool(
                    alertar_gestor(
                        cabecalho_agente("vigia_datadog", "⚠️ *Vigia Datadog*") + f"\n\n{msg}",
                        chave="vigia_datadog:aviso",
                        cooldown_segundos=DATADOG_VIGIA_ALERTA_COOLDOWN_SEG,
                        agente_id="vigia_datadog",
                    )
                )

        incrementar(
            "vigia_datadog.rodadas",
            tags=[f"ok:{analise.get('ok')}", f"critico:{analise.get('tem_critico')}"],
        )

        logger.info(
            "Vigia Datadog: ok=%s inatividades=%s erros=%s alerta=%s",
            analise.get("ok"),
            analise.get("total_inatividades"),
            analise.get("total_erros"),
            alerta_enviado,
        )
        return {
            "ok": True,
            "saudavel": analise.get("ok"),
            "tem_critico": analise.get("tem_critico"),
            "alerta_enviado": alerta_enviado,
            "analise": analise,
            "snapshot": str(SNAPSHOT_PATH),
        }
    except Exception as exc:
        logger.error("Vigia Datadog erro: %s", exc)
        incrementar("vigia_datadog.erro")
        return {"ok": False, "erro": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vigia erros Datadog e inatividade")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Vigia Datadog ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    if not out.get("saudavel"):
        logger.warning("Vigia: problemas detectados (crítico=%s)", out.get("tem_critico"))
        if DATADOG_VIGIA_FALHAR_PROCESSO:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
