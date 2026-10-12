"""
agentes/relatorio_financeiro.py
Relatório semanal de impacto financeiro estimado (repricing + ads ML).
Somente leitura — não aplica preço nem pausa campanhas.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from core.config import ML_ADS_ACOS_DIAS_LIMITE
from core.notificador import alertar_gestor

logger = logging.getLogger("relatorio_financeiro")

_COOLDOWN_SEMANAL_SEG = 7 * 24 * 3600


def _chave_cooldown_semanal() -> str:
    ano, semana, _ = datetime.now().isocalendar()
    return f"relatorio_financeiro:{ano}-W{semana:02d}"


def _gasto_diario_campanhas_acos_alto(ads: dict) -> float:
    acima = ads.get("campanhas_acos_alto") or []
    gasto_periodo = sum(float(c.get("cost") or 0) for c in acima)
    return round(gasto_periodo / max(1, ML_ADS_ACOS_DIAS_LIMITE), 2)


def _montar_mensagem(economia: float, total_ajustes: int, gasto_diario_ads: float) -> str:
    return (
        "💰 Relatório financeiro semanal — Robo-Markplaces\n"
        f"Repricing: R${economia:.2f} protegidos (piso de margem) em {total_ajustes} ajustes\n"
        f"Ads: R${gasto_diario_ads:.2f}/dia em campanhas com ACOS acima do limite (revisar/pausar)"
    )


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    """
    Coleta métricas de repricing (dry-run) e ads ML.
    Retorna ok=True quando a coleta conclui; alerta_enviado indica Telegram.
    """
    logger.info("=== Relatório financeiro semanal ===")
    try:
        from agentes.ml.agente_monitor_ml import analisar as monitor_analisar
        from agentes.repricing.agente_repricing_marketplaces import executar as repricing_executar

        repricing = repricing_executar(dry_run=True)
        economia = float(repricing.get("economia_estimada_piso_margem") or 0)
        total_ajustes = int(repricing.get("total_ajustes") or 0)

        monitor = monitor_analisar(enviar_alerta=False)
        ads = monitor.get("ads") or {} if monitor.get("ok") else {}
        gasto_diario_ads = _gasto_diario_campanhas_acos_alto(ads)

        msg = _montar_mensagem(economia, total_ajustes, gasto_diario_ads)
        logger.info(
            "Relatório financeiro: economia=%.2f ajustes=%s gasto_ads_dia=%.2f",
            economia,
            total_ajustes,
            gasto_diario_ads,
        )

        alerta_enviado = False
        if enviar_alerta:
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=_chave_cooldown_semanal(),
                    cooldown_segundos=_COOLDOWN_SEMANAL_SEG,
                )
            )
            if not alerta_enviado:
                logger.info(
                    "Relatório financeiro: alerta não enviado (cooldown semanal ou Telegram indisponível)"
                )

        return {
            "ok": True,
            "economia_estimada_piso_margem": economia,
            "total_ajustes": total_ajustes,
            "gasto_ads_dia": gasto_diario_ads,
            "alerta_enviado": alerta_enviado,
            "resumo": f"R${economia:.2f}, {total_ajustes} ajustes, ads R${gasto_diario_ads:.2f}/dia",
        }
    except Exception as exc:
        logger.error("Relatório financeiro erro: %s", exc)
        return {"ok": False, "erro": str(exc)}


def main() -> int:
    return 0 if executar().get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
