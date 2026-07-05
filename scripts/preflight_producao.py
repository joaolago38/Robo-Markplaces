#!/usr/bin/env python3
"""
scripts/preflight_producao.py
Valida credenciais críticas antes de orquestradores (Telegram + tokens OAuth).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass


def main() -> int:
    from scripts.preflight_monitor_telegram import main as preflight_telegram

    codigo = int(preflight_telegram())
    if codigo != 0:
        return codigo

    erros: list[str] = []
    try:
        from core.config import ML_CLIENT_ID, ML_REFRESH_TOKEN
        from core.token_manager import get_token_ml

        if ML_CLIENT_ID and ML_REFRESH_TOKEN:
            token = get_token_ml(forcar=True)
            if not token:
                erros.append("Mercado Livre: falha ao renovar access token")
            else:
                print("OK: Mercado Livre token renovado")
        else:
            print("INFO: Mercado Livre OAuth não configurado — pulando")
    except Exception as exc:
        erros.append(f"Mercado Livre: {exc}")

    if erros:
        for e in erros:
            print(f"AVISO: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
