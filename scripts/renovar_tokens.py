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
    tem_bling = _tem_credenciais(["BLING_CLIENT_ID", "BLING_CLIENT_SECRET", "BLING_REFRESH_TOKEN"])
    if not tem_bling:
        print("  Sem CLIENT_ID/SECRET/REFRESH_TOKEN — renovacao manual via pegar_token_bling.py")
    else:
        try:
            from core.token_manager import renovar_token_bling_detalhado
            res_bling = renovar_token_bling_detalhado()
            if res_bling.get("ok"):
                print("  bling: ok — token renovado")
                novo_refresh = res_bling.get("refresh_token")
                print("  ATENCAO: o Bling rotaciona o refresh_token a cada renovacao.")
                print("  Atualize os secrets com os novos valores abaixo, senao a")
                print("  proxima execucao falhara (o refresh_token antigo foi invalidado):")
                print(f"    BLING_ACCESS_TOKEN  -> {res_bling.get('access_token')}")
                print(f"    BLING_REFRESH_TOKEN -> {novo_refresh}")
            else:
                print(f"  bling: falhou — {res_bling.get('motivo', '')}")
                print("  Se o refresh_token expirou, gere um novo com pegar_token_bling.py")
                exit_code = 1
        except Exception as exc:
            print(f"  bling: ERRO — {exc}")
            print("  Renovacao manual via pegar_token_bling.py")
            exit_code = 1

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