"""
testar_magalu.py
Diagnóstico da renovação do token Magalu (refresh_token).

Lê MAGALU_CLIENT_ID, MAGALU_CLIENT_SECRET e MAGALU_REFRESH_TOKEN do .env,
tenta renovar via POST https://id.magalu.com/oauth/token e imprime status +
corpo da resposta (útil para diagnosticar 400 invalid_grant / invalid_client).

Uso:
    python testar_magalu.py
"""
from __future__ import annotations

import os
import urllib.parse

import requests

TOKEN_URL = "https://id.magalu.com/oauth/token"


def _carregar_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass


def carregar_credenciais() -> dict:
    """Lê credenciais Magalu do ambiente (.env via load_dotenv)."""
    _carregar_dotenv()
    return {
        "client_id": os.getenv("MAGALU_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("MAGALU_CLIENT_SECRET", "").strip(),
        "refresh_token": os.getenv("MAGALU_REFRESH_TOKEN", "").strip(),
    }


def mascarar(valor: str) -> str:
    """Versão mascarada para log — nunca expõe o valor inteiro."""
    v = (valor or "").strip()
    if not v:
        return "(vazio)"
    if len(v) <= 8:
        return f"**** (tam={len(v)})"
    return f"{v[:4]}...{v[-4:]} (tam={len(v)})"


def renovar(client_id: str, client_secret: str, refresh_token: str) -> tuple[int, str]:
    """POST refresh_token no ID Magalu. Retorna (status_code, corpo_texto)."""
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }
    )
    r = requests.post(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=25,
    )
    return r.status_code, r.text or ""


def main() -> int:
    creds = carregar_credenciais()
    cid = creds["client_id"]
    secret = creds["client_secret"]
    refresh = creds["refresh_token"]

    print("=== Diagnóstico Magalu (renovação refresh_token) ===")
    print(f"MAGALU_CLIENT_ID:     {mascarar(cid)}")
    print(f"MAGALU_CLIENT_SECRET: {mascarar(secret)}")
    print(f"MAGALU_REFRESH_TOKEN: {mascarar(refresh)}")

    if not all([cid, secret, refresh]):
        print("\nAVISO: defina MAGALU_CLIENT_ID, MAGALU_CLIENT_SECRET e MAGALU_REFRESH_TOKEN no .env")
        return 1

    print("\nEnviando POST para id.magalu.com/oauth/token ...")
    status, corpo = renovar(cid, secret, refresh)
    print(f"Status: {status}")
    print(f"Corpo:  {corpo[:500]}")

    if status < 400:
        print("\nOK — renovação aceita pelo servidor (verifique access_token no corpo).")
        return 0

    print("\nFALHA — veja o corpo acima (ex.: invalid_grant, invalid_client).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
