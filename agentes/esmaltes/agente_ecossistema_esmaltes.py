"""
agentes/esmaltes/agente_ecossistema_esmaltes.py
Consolida snapshots de esmaltes/manicures num plano de ecossistema:
cor atrai → kit + anexos + B2B pagam.

Não faz scrape novo: só lê logs já gerados pelos monitores.

Uso:
  python -m agentes.esmaltes.agente_ecossistema_esmaltes
  python -m agentes.esmaltes.agente_ecossistema_esmaltes --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import (
    ECOSSISTEMA_ESMALTES_ALERTA,
    ECOSSISTEMA_ESMALTES_ATIVO,
    ECOSSISTEMA_ESMALTES_COOLDOWN_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from core.prontidao import pode_alertar_esmaltes
from integracoes.esmaltes.ecossistema_esmaltes import (
    coletar_fontes,
    montar_mensagem_telegram,
    montar_plano,
)

logger = logging.getLogger("agente_ecossistema_esmaltes")

SNAPSHOT_PATH = ROOT / "logs" / "ecossistema_esmaltes_ultima.json"
HISTORY_PATH = ROOT / "logs" / "ecossistema_esmaltes_historico.json"


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    """Monta plano do ecossistema e alerta o gestor. Nunca lança."""
    try:
        if not ECOSSISTEMA_ESMALTES_ATIVO:
            return {"ok": False, "motivo": "agente_desligado", "alerta_enviado": False}

        pode_alertar, motivo = (True, "ok")
        if enviar_alerta:
            pode_alertar, motivo = pode_alertar_esmaltes()
            if not pode_alertar:
                logger.warning("Telegram esmaltes bloqueado: %s", motivo)
            elif not gestor_telegram_configurado():
                logger.warning("Telegram gestor não configurado")

        fontes = coletar_fontes()
        plano = montar_plano(fontes)
        msg = montar_mensagem_telegram(plano)

        payload = {
            **plano,
            "mensagem": msg,
        }
        escrever_json_atomico(SNAPSHOT_PATH, payload)

        # histórico curto (últimas 20 rodadas)
        from core.atomic_io import ler_json

        hist = ler_json(HISTORY_PATH, default={"rodadas": []})
        if not isinstance(hist, dict):
            hist = {"rodadas": []}
        rodadas = list(hist.get("rodadas") or [])
        rodadas.append(
            {
                "timestamp": plano.get("timestamp"),
                "score_ecossistema": plano.get("score_ecossistema"),
                "cobertura_fontes_pct": plano.get("cobertura_fontes_pct"),
                "top_titulos": [a.get("titulo") for a in (plano.get("top_7d") or [])[:3]],
            }
        )
        hist["rodadas"] = rodadas[-20:]
        hist["ultima"] = plano.get("timestamp")
        escrever_json_atomico(HISTORY_PATH, hist)

        gauge("ecossistema_esmaltes.score", float(plano.get("score_ecossistema") or 0))
        gauge("ecossistema_esmaltes.cobertura", float(plano.get("cobertura_fontes_pct") or 0))
        gauge("ecossistema_esmaltes.acoes", float(len(plano.get("acoes") or [])))

        enviado = False
        if (
            enviar_alerta
            and ECOSSISTEMA_ESMALTES_ALERTA
            and pode_alertar
            and plano.get("ok")
            and msg
        ):
            enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_resumo_periodo("ecossistema_esmaltes", horas_por_bucket=12),
                    cooldown_segundos=ECOSSISTEMA_ESMALTES_COOLDOWN_SEG,
                    agente_id="ecossistema_esmaltes",
                )
            )

        incrementar("ecossistema_esmaltes.ok")
        return {
            "ok": True,
            "alerta_enviado": enviado,
            "score_ecossistema": plano.get("score_ecossistema"),
            "cobertura_fontes_pct": plano.get("cobertura_fontes_pct"),
            "acoes": len(plano.get("acoes") or []),
            "top_7d": len(plano.get("top_7d") or []),
            "mensagem": msg,
        }
    except Exception as exc:
        logger.error("agente_ecossistema_esmaltes erro: %s", exc)
        incrementar("ecossistema_esmaltes.erro")
        return {"ok": False, "erro": str(exc), "alerta_enviado": False}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Ecossistema esmaltes — plano de reprodução")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args()
    out = executar(enviar_alerta=not args.sem_alerta)
    print(
        {
            "ok": out.get("ok"),
            "erro": out.get("erro"),
            "motivo": out.get("motivo"),
            "alerta_enviado": out.get("alerta_enviado"),
            "score_ecossistema": out.get("score_ecossistema"),
            "cobertura_fontes_pct": out.get("cobertura_fontes_pct"),
            "acoes": out.get("acoes"),
        }
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
