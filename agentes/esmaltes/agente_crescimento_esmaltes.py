"""
agentes/esmaltes/agente_crescimento_esmaltes.py
KPI semanal + alerta de kits sem MLB + checklist do que falta.

Uso:
  python -m agentes.esmaltes.agente_crescimento_esmaltes
  python -m agentes.esmaltes.agente_crescimento_esmaltes --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    CRESCIMENTO_ESMALTES_ALERTA,
    CRESCIMENTO_ESMALTES_ATIVO,
    CRESCIMENTO_ESMALTES_COOLDOWN_SEG,
    CRESCIMENTO_ESMALTES_META_KITS_PCT,
    CRESCIMENTO_ESMALTES_META_MARGEM_PCT,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from core.prontidao import pode_alertar_esmaltes
from integracoes.esmaltes.crescimento_esmaltes import montar_mensagem_telegram, montar_relatorio

logger = logging.getLogger("agente_crescimento_esmaltes")

SNAPSHOT_PATH = ROOT / "logs" / "crescimento_esmaltes_ultima.json"
HISTORY_PATH = ROOT / "logs" / "crescimento_esmaltes_historico.json"
CHECKLIST_PATH = ROOT / "logs" / "crescimento_esmaltes_checklist.json"


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    """Gera relatório de crescimento/gaps. Nunca lança."""
    try:
        if not CRESCIMENTO_ESMALTES_ATIVO:
            return {"ok": False, "motivo": "agente_desligado", "alerta_enviado": False}

        pode_alertar, motivo = (True, "ok")
        if enviar_alerta:
            pode_alertar, motivo = pode_alertar_esmaltes()
            if not pode_alertar:
                logger.warning("Telegram esmaltes bloqueado: %s", motivo)
            elif not gestor_telegram_configurado():
                logger.warning("Telegram gestor não configurado")

        rel = montar_relatorio(
            meta_kits_pct=CRESCIMENTO_ESMALTES_META_KITS_PCT,
            meta_margem_pct=CRESCIMENTO_ESMALTES_META_MARGEM_PCT,
        )
        msg = montar_mensagem_telegram(rel)
        payload = {**rel, "mensagem": msg}
        escrever_json_atomico(SNAPSHOT_PATH, payload)
        escrever_json_atomico(
            CHECKLIST_PATH,
            {
                "timestamp": rel.get("timestamp"),
                "checklist": rel.get("checklist") or [],
                "resumo": rel.get("resumo") or {},
            },
        )

        hist = ler_json(HISTORY_PATH, default={"rodadas": []})
        if not isinstance(hist, dict):
            hist = {"rodadas": []}
        rodadas = list(hist.get("rodadas") or [])
        rodadas.append(
            {
                "timestamp": rel.get("timestamp"),
                "critico": rel.get("critico"),
                "kits_sem_mlb": (rel.get("resumo") or {}).get("kits_sem_mlb"),
                "kits_pct": (rel.get("kpis") or {}).get("kits_pct_receita"),
                "margem": (rel.get("kpis") or {}).get("margem_media_pct"),
            }
        )
        hist["rodadas"] = rodadas[-30:]
        hist["ultima"] = rel.get("timestamp")
        escrever_json_atomico(HISTORY_PATH, hist)

        kpis = rel.get("kpis") or {}
        if kpis.get("kits_pct_receita") is not None:
            gauge("crescimento_esmaltes.kits_pct", float(kpis["kits_pct_receita"]))
        if kpis.get("margem_media_pct") is not None:
            gauge("crescimento_esmaltes.margem_pct", float(kpis["margem_media_pct"]))
        gauge(
            "crescimento_esmaltes.kits_sem_mlb",
            float((rel.get("resumo") or {}).get("kits_sem_mlb") or 0),
        )

        enviado = False
        if (
            enviar_alerta
            and CRESCIMENTO_ESMALTES_ALERTA
            and pode_alertar
            and msg
        ):
            # crítico → bucket menor para insistir; senão semanal
            horas = 12 if rel.get("critico") else 24
            enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_resumo_periodo("crescimento_esmaltes", horas_por_bucket=horas),
                    cooldown_segundos=CRESCIMENTO_ESMALTES_COOLDOWN_SEG,
                    agente_id="crescimento_esmaltes",
                )
            )

        incrementar("crescimento_esmaltes.ok")
        return {
            "ok": True,
            "alerta_enviado": enviado,
            "critico": rel.get("critico"),
            "kits_sem_mlb": (rel.get("resumo") or {}).get("kits_sem_mlb"),
            "checklist": len(rel.get("checklist") or []),
            "kpis": kpis,
            "mensagem": msg,
        }
    except Exception as exc:
        logger.error("agente_crescimento_esmaltes erro: %s", exc)
        incrementar("crescimento_esmaltes.erro")
        return {"ok": False, "erro": str(exc), "alerta_enviado": False}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Crescimento esmaltes — KPI + gaps")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args()
    out = executar(enviar_alerta=not args.sem_alerta)
    print(
        {
            "ok": out.get("ok"),
            "erro": out.get("erro"),
            "motivo": out.get("motivo"),
            "alerta_enviado": out.get("alerta_enviado"),
            "critico": out.get("critico"),
            "kits_sem_mlb": out.get("kits_sem_mlb"),
            "checklist": out.get("checklist"),
        }
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
