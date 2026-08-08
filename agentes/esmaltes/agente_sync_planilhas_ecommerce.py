# -*- coding: utf-8 -*-
"""
agentes/esmaltes/agente_sync_planilhas_ecommerce.py

Sincroniza planilhas_ecommerce → catalogo/*.json + produtos.json + métricas Datadog.

Uso:
  python -m agentes.esmaltes.agente_sync_planilhas_ecommerce
  python -m agentes.esmaltes.agente_sync_planilhas_ecommerce --sem-metricas
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

logger = logging.getLogger("agente_sync_planilhas_ecommerce")


def executar(*, emitir_metricas: bool = True) -> dict[str, Any]:
    try:
        from integracoes.esmaltes.planilha_consolidado_ecommerce import (
            sincronizar_planilhas_ecommerce,
        )

        out = sincronizar_planilhas_ecommerce(emitir_metricas=emitir_metricas)
        if out.get("ok"):
            logger.info(
                "sync planilhas ok: plano=%s cruzeiro=%s invest=R$%s oport=%s livia=%s",
                out.get("plano_validacao"),
                out.get("kits_cruzeiro"),
                out.get("invest_total_reais"),
                out.get("oportunidades"),
                out.get("livia"),
            )
        else:
            logger.warning("sync planilhas falhou: %s", out.get("erro"))
        return out
    except Exception as exc:
        logger.error("agente_sync_planilhas_ecommerce: %s", exc)
        return {"ok": False, "erro": str(exc)}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Sync planilhas ecommerce → catálogo")
    parser.add_argument("--sem-metricas", action="store_true")
    args = parser.parse_args()
    out = executar(emitir_metricas=not args.sem_metricas)
    print(
        {
            "ok": out.get("ok"),
            "erro": out.get("erro"),
            "plano_validacao": out.get("plano_validacao"),
            "kits_cruzeiro": out.get("kits_cruzeiro"),
            "invest_total_reais": out.get("invest_total_reais"),
            "oportunidades": out.get("oportunidades"),
            "livia": out.get("livia"),
            "produtos": out.get("produtos"),
        }
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
