#!/usr/bin/env python3
"""
Renova tokens de acesso (Mercado Livre, Shopee e Magazine Luiza).
Útil localmente antes de rodar agentes ou em CI para validar credenciais.

Não imprime valores de tokens — apenas status por marketplace.

Uso:
    python scripts/renovar_tokens.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.token_manager import renovar_todos_tokens  # noqa: E402


def main() -> int:
    resultados = renovar_todos_tokens()
    exit_code = 0
    for nome, payload in sorted(resultados.items()):
        ok = payload.get("ok")
        linha = f"{nome}: {'ok' if ok else 'falhou'}"
        print(linha)
        if ok is False:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
