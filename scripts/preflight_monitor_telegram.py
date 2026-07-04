#!/usr/bin/env python3
"""
scripts/preflight_monitor_telegram.py

Valida TELEGRAM_TOKEN + TELEGRAM_GESTOR_CHAT_ID antes dos agentes de monitor.
Usado nos workflows de leilão e Alibaba para falhar cedo se o Telegram estiver cego.

Uso:
    python scripts/preflight_monitor_telegram.py
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
    from core.config import TELEGRAM_GESTOR_CHAT_ID, TELEGRAM_TOKEN
    from core.http_client import request
    from core.http_errors import mascarar_url_telegram

    faltando = []
    if not (TELEGRAM_TOKEN or "").strip():
        faltando.append("TELEGRAM_TOKEN")
    if not (TELEGRAM_GESTOR_CHAT_ID or "").strip():
        faltando.append("TELEGRAM_GESTOR_CHAT_ID")
    if faltando:
        print(f"FALHA: variáveis ausentes: {', '.join(faltando)}")
        return 1

    try:
        r = request(
            "GET",
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe",
            timeout=15,
        )
        r.raise_for_status()
        body = r.json()
        if not body.get("ok"):
            print("FALHA: getMe retornou ok=false — token inválido ou revogado")
            return 1
        username = body.get("result", {}).get("username", "?")
        print(f"OK: bot @{username} | gestor chat configurado")
        return 0
    except Exception as exc:
        print(f"FALHA: getMe — {mascarar_url_telegram(str(exc))}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
