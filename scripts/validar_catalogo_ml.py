#!/usr/bin/env python3
"""
scripts/validar_catalogo_ml.py
Lista SKUs ativos com item_id MLB_PREENCHER / inválido.
Exit 1 se --strict e houver placeholders (CI opcional).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 se houver ativos com MLB placeholder",
    )
    parser.add_argument(
        "--alerta",
        action="store_true",
        help="Envia alerta Telegram gestor se houver placeholders",
    )
    args = parser.parse_args()

    from core.produto_lookup import listar_ativos_com_mlb_placeholder

    ruins = listar_ativos_com_mlb_placeholder()
    if not ruins:
        print("OK: nenhum SKU ativo com MLB_PREENCHER / item_id inválido")
        return 0

    print(f"AVISO: {len(ruins)} SKU(s) ativos sem MLB real:")
    for r in ruins[:20]:
        print(f"  - {r['sku']}: {r['item_id']} — {r['nome']}")

    if args.alerta:
        try:
            from core.notificador import alertar_gestor

            linhas = "\n".join(f"• {r['sku']} → {r['item_id']}" for r in ruins[:12])
            alertar_gestor(
                "⚠️ *Catálogo ML incompleto*\n\n"
                f"{len(ruins)} SKU(s) ativos ainda com `MLB_PREENCHER`.\n"
                "Conversão/boost e sync reais ficam bloqueados até preencher.\n\n"
                f"{linhas}\n\n_Use scripts/preencher_item_id_ml.py_",
                chave="catalogo:mlb_preencher",
                cooldown_segundos=86400,
            )
        except Exception as exc:
            print(f"alerta Telegram falhou: {exc}", file=sys.stderr)

    if args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
