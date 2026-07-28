"""
agentes/infra/agente_consumo_claude.py
Reporta no Telegram o consumo Claude (US$ / restante / por agente) + gráficos PNG.

Uso:
  python -m agentes.infra.agente_consumo_claude
  python -m agentes.infra.agente_consumo_claude --sem-alerta
  python -m agentes.infra.agente_consumo_claude --reset
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.claude_orcamento import (
    gerar_graficos_consumo,
    montar_mensagem_telegram,
    ranking_consumo_por_agente,
    resetar_consumo,
    resumo,
)
from core.config import (
    CLAUDE_ORCAMENTO_ALERTA,
    CLAUDE_ORCAMENTO_USD,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, enviar_foto_gestor

logger = logging.getLogger("agente_consumo_claude")
SNAPSHOT_PATH = ROOT / "logs" / "consumo_claude_ultima.json"


def executar(*, enviar_alerta: bool = True, reset: bool = False) -> dict[str, Any]:
    try:
        if reset:
            r = resetar_consumo(manter_orcamento=True)
        else:
            r = resumo()
        graficos = gerar_graficos_consumo(r)
        ranking = graficos.get("ranking") or ranking_consumo_por_agente(r)
        msg = montar_mensagem_telegram(r, titulo="Claude — orçamento + assertividade")
        payload = {
            "ok": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "orcamento_usd": CLAUDE_ORCAMENTO_USD,
            "resumo": r,
            "ranking_agentes": ranking,
            "graficos": {
                "por_agente": graficos.get("por_agente"),
                "evolucao": graficos.get("evolucao"),
                "metrica_barras": graficos.get("metrica_barras"),
                "historico_pontos": graficos.get("historico_pontos"),
            },
            "assertividade_pct": r.get("assertividade_pct"),
            "mensagem": msg,
        }
        escrever_json_atomico(SNAPSHOT_PATH, payload)
        gauge("claude.orcamento_consumido_usd", float(r.get("consumido_usd") or 0))
        gauge("claude.orcamento_restante_usd", float(r.get("restante_usd") or 0))
        gauge("claude.assertividade_pct", float(r.get("assertividade_pct") or 0))

        enviado = False
        chave = chave_resumo_periodo("consumo_claude", horas_por_bucket=6)
        if enviar_alerta and CLAUDE_ORCAMENTO_ALERTA and msg:
            enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave,
                    cooldown_segundos=1,
                    agente_id="consumo_claude",
                    _ignorar_cooldown=True,
                )
            )
            path_barras = graficos.get("por_agente")
            if path_barras:
                enviar_foto_gestor(
                    str(path_barras),
                    "Claude — valor consumido por agente",
                    chave=f"{chave}:grafico_agentes",
                    cooldown_segundos=1,
                    _ignorar_cooldown=True,
                )
            path_ev = graficos.get("evolucao")
            if path_ev:
                enviar_foto_gestor(
                    str(path_ev),
                    "Claude — andamento do consumo (US$ / restante / %)",
                    chave=f"{chave}:grafico_evolucao",
                    cooldown_segundos=1,
                    _ignorar_cooldown=True,
                )
        incrementar("consumo_claude.ok")
        return {
            "ok": True,
            "alerta_enviado": enviado,
            "resumo": r,
            "ranking_agentes": ranking,
            "graficos": graficos,
        }
    except Exception as exc:
        logger.error("agente_consumo_claude: %s", exc)
        incrementar("consumo_claude.erro")
        return {"ok": False, "erro": str(exc), "alerta_enviado": False}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Painel consumo Claude → Telegram + gráficos")
    p.add_argument("--sem-alerta", action="store_true")
    p.add_argument("--reset", action="store_true", help="Zera contadores locais")
    args = p.parse_args()
    out = executar(enviar_alerta=not args.sem_alerta, reset=args.reset)
    ranking = out.get("ranking_agentes") or []
    print(
        {
            "ok": out.get("ok"),
            "alerta_enviado": out.get("alerta_enviado"),
            "consumido": (out.get("resumo") or {}).get("consumido_usd"),
            "restante": (out.get("resumo") or {}).get("restante_usd"),
            "assertividade": (out.get("resumo") or {}).get("assertividade_pct"),
            "bloqueado": (out.get("resumo") or {}).get("bloqueado"),
            "agentes": [
                {
                    "agente": row.get("agente"),
                    "usd": row.get("usd"),
                    "chamadas": row.get("chamadas"),
                }
                for row in ranking[:10]
            ],
            "grafico_por_agente": (out.get("graficos") or {}).get("por_agente"),
            "grafico_evolucao": (out.get("graficos") or {}).get("evolucao"),
            "erro": out.get("erro"),
        }
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
