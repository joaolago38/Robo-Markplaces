#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    print("=" * 60)
    print("Renovacao de tokens — Robo-Markplaces")
    print("=" * 60)

    exit_code = 0

    print("\n[Bling]")
    print("  Renovacao manual — use pegar_token_bling.py")

    print("\n[ML / Shopee / Magalu]")
    try:
        from core.token_manager import renovar_todos_tokens
        resultados = renovar_todos_tokens()
        for nome, payload in sorted(resultados.items()):
            ok = payload.get("ok")
            print(f"  {nome}: {'ok' if ok else 'falhou'}")
            if ok is False:
                exit_code = 1
    except Exception as exc:
        print(f"  ERRO: {exc}")
        exit_code = 1

    print("\n" + "=" * 60)
    print(f"Concluido — exit code: {exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())