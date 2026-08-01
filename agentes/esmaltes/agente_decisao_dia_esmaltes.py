"""
agentes/esmaltes/agente_decisao_dia_esmaltes.py
Um card por dia: FAZER · NÃO FAZER · CUSTO DE NÃO FAZER.

Uso:
  python -m agentes.esmaltes.agente_decisao_dia_esmaltes
  python -m agentes.esmaltes.agente_decisao_dia_esmaltes --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    CRESCIMENTO_ESMALTES_META_KITS_PCT,
    CRESCIMENTO_ESMALTES_META_MARGEM_PCT,
    DECISAO_DIA_ESMALTES_ALERTA,
    DECISAO_DIA_ESMALTES_ATIVO,
    DECISAO_DIA_ESMALTES_COOLDOWN_SEG,
    DECISAO_DIA_ESMALTES_GUERRA_CATALOGO,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from core.prontidao import pode_alertar_esmaltes
from integracoes.esmaltes.decisao_dia_esmaltes import (
    HISTORICO_KPI_PATH,
    montar_decisao,
    montar_mensagem_telegram,
)

logger = logging.getLogger("agente_decisao_dia_esmaltes")

SNAPSHOT_PATH = ROOT / "logs" / "decisao_dia_esmaltes_ultima.json"
HISTORY_PATH = ROOT / "logs" / "decisao_dia_esmaltes_historico.json"


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    """Monta veredito do dia e alerta. Nunca lança."""
    try:
        if not DECISAO_DIA_ESMALTES_ATIVO:
            return {"ok": False, "motivo": "agente_desligado", "alerta_enviado": False}

        pode_alertar, motivo = (True, "ok")
        if enviar_alerta:
            pode_alertar, motivo = pode_alertar_esmaltes()
            if not pode_alertar:
                logger.warning("Telegram esmaltes bloqueado: %s", motivo)
            elif not gestor_telegram_configurado():
                logger.warning("Telegram gestor não configurado")

        dec = montar_decisao(
            margem_piso_pct=CRESCIMENTO_ESMALTES_META_MARGEM_PCT,
            meta_kits_pct=CRESCIMENTO_ESMALTES_META_KITS_PCT,
            caminho_guerra=DECISAO_DIA_ESMALTES_GUERRA_CATALOGO,
        )
        msg = montar_mensagem_telegram(dec)

        # grava evolução KPI (mantém últimos 60 pontos)
        pontos = list(dec.pop("_pontos_kpi", None) or [])
        escrever_json_atomico(HISTORICO_KPI_PATH, {"pontos": pontos[-60:]})

        payload = {**dec, "mensagem": msg}
        escrever_json_atomico(SNAPSHOT_PATH, payload)

        hist = ler_json(HISTORY_PATH, default={"rodadas": []})
        if not isinstance(hist, dict):
            hist = {"rodadas": []}
        rodadas = list(hist.get("rodadas") or [])
        rodadas.append(
            {
                "timestamp": dec.get("timestamp"),
                "fazer": (dec.get("fazer") or {}).get("codigo"),
                "nao_fazer": (dec.get("nao_fazer") or {}).get("codigo"),
                "liberados": dec.get("liberados"),
                "bloqueados": dec.get("bloqueados"),
            }
        )
        hist["rodadas"] = rodadas[-45:]
        hist["ultima"] = dec.get("timestamp")
        escrever_json_atomico(HISTORY_PATH, hist)

        gauge("decisao_dia_esmaltes.liberados", float(dec.get("liberados") or 0))
        gauge("decisao_dia_esmaltes.bloqueados", float(dec.get("bloqueados") or 0))

        enviado = False
        if enviar_alerta and DECISAO_DIA_ESMALTES_ALERTA and pode_alertar and msg:
            enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_resumo_periodo("decisao_dia_esmaltes", horas_por_bucket=20),
                    cooldown_segundos=DECISAO_DIA_ESMALTES_COOLDOWN_SEG,
                    agente_id="decisao_dia_esmaltes",
                )
            )

        incrementar("decisao_dia_esmaltes.ok")
        return {
            "ok": True,
            "alerta_enviado": enviado,
            "fazer": (dec.get("fazer") or {}).get("codigo"),
            "nao_fazer": (dec.get("nao_fazer") or {}).get("codigo"),
            "liberados": dec.get("liberados"),
            "bloqueados": dec.get("bloqueados"),
            "mensagem": msg,
        }
    except Exception as exc:
        logger.error("agente_decisao_dia_esmaltes erro: %s", exc)
        incrementar("decisao_dia_esmaltes.erro")
        return {"ok": False, "erro": str(exc), "alerta_enviado": False}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Decisão do dia Impala ML")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args()
    out = executar(enviar_alerta=not args.sem_alerta)
    print(
        {
            "ok": out.get("ok"),
            "erro": out.get("erro"),
            "motivo": out.get("motivo"),
            "alerta_enviado": out.get("alerta_enviado"),
            "fazer": out.get("fazer"),
            "nao_fazer": out.get("nao_fazer"),
            "liberados": out.get("liberados"),
            "bloqueados": out.get("bloqueados"),
        }
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
