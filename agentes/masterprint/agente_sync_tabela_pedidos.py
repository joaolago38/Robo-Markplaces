# -*- coding: utf-8 -*-
"""
agentes/masterprint/agente_sync_tabela_pedidos.py

Sincroniza TABELA DE PEDIDOS (filamentos + pincéis/apagadores) → catálogo + Datadog.

Uso:
  python -m agentes.masterprint.agente_sync_tabela_pedidos
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

logger = logging.getLogger("agente_sync_tabela_pedidos")


def executar(*, emitir_metricas: bool = True) -> dict[str, Any]:
    try:
        from integracoes.masterprint.planilha_tabela_pedidos import sincronizar_tabela_pedidos

        out = sincronizar_tabela_pedidos(emitir_metricas=emitir_metricas)
        if out.get("ok"):
            tot = out.get("totais") or {}
            logger.info(
                "tabela pedidos ok: skus=%s filamentos=%s escritorio=%s",
                tot.get("skus"),
                tot.get("filamentos"),
                tot.get("escritorio"),
            )
        else:
            logger.warning("tabela pedidos falhou: %s", out.get("erro"))
        return out
    except Exception as exc:
        logger.error("agente_sync_tabela_pedidos: %s", exc)
        return {"ok": False, "erro": str(exc)}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Sync TABELA DE PEDIDOS Masterprint")
    parser.add_argument("--sem-metricas", action="store_true")
    args = parser.parse_args()
    out = executar(emitir_metricas=not args.sem_metricas)
    print(
        {
            "ok": out.get("ok"),
            "erro": out.get("erro"),
            "totais": out.get("totais"),
        }
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
