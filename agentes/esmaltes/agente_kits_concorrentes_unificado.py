"""
agentes/esmaltes/agente_kits_concorrentes_unificado.py
Índice único dos snapshots de kits (rivais esmalte + PETG com 'kit' no título).

Não busca ML. Não manda Telegram no cron (o arquivo é o entregável).

  python -m agentes.esmaltes.agente_kits_concorrentes_unificado
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

from core.datadog_metrics import incrementar
from integracoes.esmaltes.kits_concorrentes_unificado import SNAPSHOT_PATH, processar

logger = logging.getLogger("agente_kits_concorrentes_unificado")


def executar(*, enviar_alerta: bool = False) -> dict[str, Any]:
    try:
        out = processar(persistir=True)
        incrementar("agente_kits_concorrentes_unificado.ok")
        if enviar_alerta:
            logger.info("unificado kits gravado em %s (sem Telegram)", SNAPSHOT_PATH.name)
        return out
    except Exception as exc:
        logger.error("agente_kits_concorrentes_unificado: %s", exc)
        incrementar("agente_kits_concorrentes_unificado.erro")
        return {"ok": False, "erro": str(exc)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args()
    snap = executar(enviar_alerta=not args.sem_alerta)
    esm = snap.get("esmaltes") if isinstance(snap.get("esmaltes"), dict) else {}
    fil = snap.get("filamentos") if isinstance(snap.get("filamentos"), dict) else {}
    print(
        f"ok={snap.get('ok')} fontes={snap.get('fontes_presentes')}/{snap.get('fontes_total')} "
        f"rivais={esm.get('n_rivais')} filamento_kit={fil.get('kits_no_titulo')} "
        f"arquivo={SNAPSHOT_PATH}"
    )
