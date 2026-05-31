#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CREDENCIAIS_ML = ["ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN"]
CREDENCIAIS_SHOPEE = ["SHOPEE_PARTNER_ID", "SHOPEE_PARTNER_KEY", "SHOPEE_SHOP_ID"]
CREDENCIAIS_MAGALU = ["MAGALU_CLIENT_ID", "MAGALU_CLIENT_SECRET", "MAGALU_MERCHANT_ID"]

def _tem_credenciais(variaveis: list[str]) -> bool:
    return all(os.getenv(v, "").strip() for v in variaveis)


def main() -> int:
    print("=" * 60)
    print("Renovacao de tokens — Robo-Markplaces")
    print("=" * 60)

    exit_code = 0

    print("\n[Bling]")
    print("  Renovacao manual — use pegar_token_bling.py")

    print("\n[ML / Shopee / Magalu]")

    tem_ml     = _tem_credenciais(CREDENCIAIS_ML)
    tem_shopee = _tem_credenciais(CREDENCIAIS_SHOPEE)
    tem_magalu = _tem_credenciais(CREDENCIAIS_MAGALU)

    if not tem_ml and not tem_shopee and not tem_magalu:
        print("  Nenhuma credencial configurada — ignorado")
        print("\n" + "=" * 60)
        print(f"Concluido — exit code: {exit_code}")
        return exit_code

    try:
        from core.token_manager import renovar_todos_tokens
        resultados = renovar_todos_tokens()

        ignorar = {
            "mercadolivre": not tem_ml,
            "shopee":       not tem_shopee,
            "magalu":       not tem_magalu,
        }

        for nome, payload in sorted(resultados.items()):
            ok = payload.get("ok")
            if ignorar.get(nome):
                print(f"  {nome}: sem credenciais — ignorado")
            elif ok:
                print(f"  {nome}: ok")
            else:
                motivo = payload.get("motivo", "")
                print(f"  {nome}: falhou — {motivo}")
                exit_code = 1

    except Exception as exc:
        print(f"  ERRO: {exc}")
        exit_code = 1

    print("\n" + "=" * 60)
    print(f"Concluido — exit code: {exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())