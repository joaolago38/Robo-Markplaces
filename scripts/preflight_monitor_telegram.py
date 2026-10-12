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
    from core.telegram_gate import token_formato_valido, verificar_token

    faltando = []
    if not (TELEGRAM_TOKEN or "").strip():
        faltando.append("TELEGRAM_TOKEN")
    if not (TELEGRAM_GESTOR_CHAT_ID or "").strip():
        faltando.append("TELEGRAM_GESTOR_CHAT_ID")
    if faltando:
        print(f"FALHA: variáveis ausentes: {', '.join(faltando)}")
        return 1
    if not token_formato_valido():
        print("FALHA: TELEGRAM_TOKEN com formato inválido (use o token do @BotFather)")
        return 1
    if not verificar_token(forcar=True):
        print("FALHA: getMe — token inválido ou revogado (HTTP 404)")
        return 1
    print("OK: bot validado | gestor chat configurado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
