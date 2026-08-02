"""
agentes/importacao/agente_alibaba_sourcing.py
Um run: busca Alibaba (catálogo) + inteligência (câmbio/landed/margem).

Os agentes individuais permanecem para testes e execução manual;
aqui o alerta principal fica na inteligência (busca sem Telegram duplicado).

Uso:
  python -m agentes.importacao.agente_alibaba_sourcing
  python -m agentes.importacao.agente_alibaba_sourcing --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import ALIBABA_SOURCING_ATIVO, ROOT
from core.datadog_metrics import gauge, incrementar

logger = logging.getLogger("agente_alibaba_sourcing")

SNAPSHOT_PATH = ROOT / "logs" / "alibaba_sourcing_ultima.json"


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    """Roda busca + inteligência. Nunca lança."""
    try:
        if not ALIBABA_SOURCING_ATIVO:
            return {"ok": False, "motivo": "agente_desligado", "alerta_enviado": False}

        from agentes.importacao import agente_alibaba_importacao as busca
        from agentes.importacao import agente_alibaba_importacao_inteligente as intel

        logger.info("alibaba_sourcing: busca catálogo")
        out_busca = busca.executar(enviar_alerta=False)

        logger.info("alibaba_sourcing: inteligencia margem")
        out_intel = intel.executar(enviar_alerta=enviar_alerta)

        ok = bool(out_busca.get("ok") or out_intel.get("ok"))
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ok": ok,
            "busca": {
                "ok": out_busca.get("ok"),
                "motivo": out_busca.get("motivo") or out_busca.get("erro"),
                "alerta_enviado": out_busca.get("alerta_enviado"),
            },
            "inteligencia": {
                "ok": out_intel.get("ok"),
                "motivo": out_intel.get("motivo") or out_intel.get("erro"),
                "alerta_enviado": out_intel.get("alerta_enviado"),
                "lucrativas": out_intel.get("lucrativas") or out_intel.get("total_lucrativas"),
            },
        }
        escrever_json_atomico(SNAPSHOT_PATH, payload)

        gauge("alibaba_sourcing.busca_ok", 1.0 if out_busca.get("ok") else 0.0)
        gauge("alibaba_sourcing.intel_ok", 1.0 if out_intel.get("ok") else 0.0)
        incrementar("alibaba_sourcing.ok" if ok else "alibaba_sourcing.erro")

        return {
            "ok": ok,
            "alerta_enviado": bool(out_intel.get("alerta_enviado")),
            "busca": out_busca,
            "inteligencia": out_intel,
        }
    except Exception as exc:
        logger.error("agente_alibaba_sourcing erro: %s", exc)
        incrementar("alibaba_sourcing.erro")
        return {"ok": False, "erro": str(exc), "alerta_enviado": False}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Alibaba sourcing consolidado")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)
    out = executar(enviar_alerta=not args.sem_alerta)
    print(
        {
            "ok": out.get("ok"),
            "erro": out.get("erro"),
            "motivo": out.get("motivo"),
            "alerta_enviado": out.get("alerta_enviado"),
        }
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
