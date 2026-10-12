"""
testar_hosts_magalu.py
Renova o access_token do Magalu (via refresh_token, igual o código de
produção faz) e testa GET /v0/questions em api.magalu.com e em
services.magalu.com, pra descobrir qual host é o correto.

Uso:
    python testar_hosts_magalu.py

Não imprime o token — só os resultados de cada host.
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import requests  # noqa: E402

from core.token_manager import get_token_magalu  # noqa: E402


def testar(host: str) -> None:
    tok = get_token_magalu()
    if not tok:
        print(f"[{host}] Não consegui obter um access_token válido (refresh falhou).")
        return
    try:
        r = requests.get(
            f"{host}/v0/questions",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            params={"limit": 1},
            timeout=15,
        )
        print(f"[{host}] status={r.status_code}")
        print(f"[{host}] body={r.text[:300]}")
    except Exception as exc:
        print(f"[{host}] erro de conexão: {exc}")
    print()


def main() -> None:
    print("=== Testando api.magalu.com ===")
    testar("https://api.magalu.com")

    print("=== Testando services.magalu.com ===")
    testar("https://services.magalu.com")


if __name__ == "__main__":
    main()
