"""
agentes/importacao/agente_logistica_china_ml.py
Ranqueia portos BR para carga China 40HC até o hub Full do Mercado Livre.

Toggle DESLIGADO por padrão (LOGISTICA_CHINA_ML_ATIVO=0). Sem cron.
Religar: LOGISTICA_CHINA_ML_ATIVO=1. Rodar na hora: --forcar.

Uso:
  python -m agentes.importacao.agente_logistica_china_ml --forcar
  python -m agentes.importacao.agente_logistica_china_ml --origem szx --hub cajamar --forcar
  python -m agentes.importacao.agente_logistica_china_ml --hub gcr --forcar --alerta
"""
from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from core.config import LOGISTICA_CHINA_ML_ATIVO
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.importacao.logistica_china_ml import (
    formatar_logistica_telegram,
    ranquear_portos_ml,
)

logger = logging.getLogger("agente_logistica_china_ml")


def executar(
    *,
    origem_id: str = "szx",
    hub_id: str = "cajamar",
    cambio_usd_brl: float | None = None,
    enviar_alerta: bool = False,
    forcar: bool = False,
) -> dict[str, Any]:
    if not LOGISTICA_CHINA_ML_ATIVO and not forcar:
        incrementar("logistica_china_ml.inativo")
        logger.warning("logistica_china_ml: LOGISTICA_CHINA_ML_ATIVO=0 — ignorado")
        return {
            "ok": False,
            "motivo": "LOGISTICA_CHINA_ML_ATIVO=0",
            "toggle_ligado": False,
            "mensagem": formatar_logistica_telegram({"ok": False, "motivo": "LOGISTICA_CHINA_ML_ATIVO=0"}),
        }

    out = ranquear_portos_ml(
        origem_id=origem_id,
        hub_id=hub_id,
        cambio_usd_brl=cambio_usd_brl,
        gravar=True,
    )
    out["toggle_ligado"] = bool(LOGISTICA_CHINA_ML_ATIVO)
    out["forcado"] = bool(forcar and not LOGISTICA_CHINA_ML_ATIVO)
    msg = formatar_logistica_telegram(out)
    out["mensagem"] = msg

    if enviar_alerta and out.get("ok") and gestor_telegram_configurado():
        try:
            alertar_gestor(
                msg,
                chave=chave_resumo_periodo("logistica_china_ml", horas_por_bucket=24),
                cooldown_segundos=86400,
                agente_id="logistica_china_ml",
            )
            incrementar("logistica_china_ml.telegram_ok")
        except Exception as exc:
            logger.warning("telegram logistica china ml: %s", exc)
            incrementar("logistica_china_ml.telegram_erro")

    logger.info(
        "logistica_china_ml: ok=%s origem=%s hub=%s melhor=%s forcar=%s",
        out.get("ok"),
        origem_id,
        hub_id,
        (out.get("melhor") or {}).get("codigo"),
        forcar,
    )
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description="China → portos BR → hub Full ML (40HC)")
    p.add_argument("--origem", default="szx", help="szx|nsa|nbo|sha|xmn|tao")
    p.add_argument(
        "--hub",
        default="cajamar",
        help="americana|cajamar|campinas|aracari|extrema|gcr|recife|fortaleza",
    )
    p.add_argument("--cambio", type=float, default=None, help="USD/BRL (senão cotação/cache)")
    p.add_argument("--alerta", action="store_true")
    p.add_argument(
        "--forcar",
        action="store_true",
        help="Roda mesmo com LOGISTICA_CHINA_ML_ATIVO=0",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    out = executar(
        origem_id=args.origem,
        hub_id=args.hub,
        cambio_usd_brl=args.cambio,
        enviar_alerta=args.alerta,
        forcar=args.forcar,
    )
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print(out.get("mensagem") or out)


if __name__ == "__main__":
    main()
