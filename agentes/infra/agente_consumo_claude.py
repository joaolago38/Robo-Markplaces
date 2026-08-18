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
    aplicar_saldo_console,
    emitir_metricas_claude_datadog,
    gerar_graficos_consumo,
    montar_mensagem_telegram,
    ranking_consumo_por_agente,
    resetar_consumo,
    resumo,
    sincronizar_saldo_real,
    talvez_sondar_saldo,
)
from core.config import (
    CLAUDE_ORCAMENTO_ALERTA,
    ROOT,
)
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, enviar_foto_gestor

logger = logging.getLogger("agente_consumo_claude")
SNAPSHOT_PATH = ROOT / "logs" / "consumo_claude_ultima.json"


def executar(
    *,
    enviar_alerta: bool = True,
    reset: bool = False,
    sincronizar: bool = True,
) -> dict[str, Any]:
    try:
        if reset:
            r = resetar_consumo(manter_orcamento=True)
        else:
            if sincronizar:
                sync = sincronizar_saldo_real(emitir_datadog=False)
                if sync.get("ok"):
                    logger.info(
                        "Claude Datadog alinhado à Cost API restante=US$ %s",
                        (sync.get("resumo") or {}).get("restante_usd"),
                    )
                else:
                    logger.info(
                        "Claude Datadog sem Cost API (%s) — usando snapshot do painel",
                        sync.get("motivo"),
                    )
            r = resumo()
        try:
            talvez_sondar_saldo()
        except Exception:
            logger.debug("sonda saldo no painel Claude falhou", exc_info=True)
        graficos = gerar_graficos_consumo(r)
        ranking = graficos.get("ranking") or ranking_consumo_por_agente(r)
        msg = montar_mensagem_telegram(r, titulo="Claude — orçamento + assertividade")
        payload = {
            "ok": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "orcamento_usd": r.get("orcamento_usd"),
            "fonte_saldo": r.get("fonte_saldo"),
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
        emitir_metricas_claude_datadog(r)

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
    p.add_argument(
        "--creditos",
        type=float,
        default=None,
        help="Saldo/créditos US$ do painel (console) → robo.claude.orcamento_restante_usd",
    )
    p.add_argument(
        "--gasto-mes",
        type=float,
        default=None,
        help="Gasto do mês US$ no painel → robo.claude.orcamento_consumido_usd",
    )
    p.add_argument("--tokens-7d", type=float, default=None, help="Volume de tokens (7 dias) do painel")
    p.add_argument(
        "--tokens-crescimento-pct",
        type=float,
        default=None,
        help="Crescimento %% tokens 7d do painel",
    )
    p.add_argument("--limite-mes", type=float, default=None, help="Limite mensal US$ do painel")
    p.add_argument(
        "--prompt-cache",
        action="store_true",
        help="Marca prompt cache como ativo no Datadog",
    )
    args = p.parse_args()
    if args.creditos is not None:
        r = aplicar_saldo_console(
            args.creditos,
            gasto_mes_usd=args.gasto_mes,
            tokens_7d=args.tokens_7d,
            tokens_7d_crescimento_pct=args.tokens_crescimento_pct,
            prompt_cache_ativo=True if args.prompt_cache else False,
            limite_mes_usd=args.limite_mes,
            emitir_datadog=True,
        )
        print(
            {
                "ok": True,
                "sync_painel": True,
                "consumido": r.get("consumido_usd"),
                "restante": r.get("restante_usd"),
                "orcamento": r.get("orcamento_usd"),
            }
        )
        if args.reset or not args.sem_alerta:
            # ainda publica o painel Telegram se pedido
            out = executar(
                enviar_alerta=not args.sem_alerta,
                reset=False,
                sincronizar=False,
            )
            print({"alerta_enviado": out.get("alerta_enviado")})
        return 0
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
