"""
pegar_token_magalu.py
Troca o code OAuth2 pelo Access Token e Refresh Token do Magalu (bootstrap inicial).

Credenciais vêm de variáveis de ambiente / .env (NUNCA hardcoded):
    MAGALU_CLIENT_ID, MAGALU_CLIENT_SECRET
    MAGALU_REDIRECT_URI   (opcional; default https://www.google.com)

Uso:
    1) Crie a aplicação no portal developers.magalu.com (ID Magalu) para obter
       MAGALU_CLIENT_ID / MAGALU_CLIENT_SECRET. Marque o perfil como aplicação
       própria (own_integration) — integração da própria loja.
    2) Abra a URL de consentimento do ID Magalu (URL/escopos vêm do portal ao
       criar a aplicação), autorize e copie o "code" da redirect_uri.
    3) Rode IMEDIATAMENTE, passando o code:
       python pegar_token_magalu.py SEU_CODE
       (ou defina MAGALU_OAUTH_CODE no ambiente)
"""
from __future__ import annotations

import os
import sys

import requests


def _carregar_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass


_carregar_dotenv()

TOKEN_URL = "https://id.magalu.com/oauth/token"

CLIENT_ID = os.getenv("MAGALU_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("MAGALU_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("MAGALU_REDIRECT_URI", "https://www.google.com").strip()


def _code_from_argv(argv: list[str] | None) -> str:
    args = argv if argv is not None else sys.argv[1:]
    if args:
        return args[0].strip()
    return os.getenv("MAGALU_OAUTH_CODE", "").strip()


def trocar_code_por_token(code: str) -> tuple[requests.Response, dict]:
    """
    Troca authorization_code por tokens. Tenta form-urlencoded primeiro;
    em 400/415 repete com JSON (alguns endpoints do Magalu aceitam só JSON).
    """
    body = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    resp = requests.post(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )

    if resp.status_code in (400, 415):
        resp = requests.post(
            TOKEN_URL,
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )

    try:
        dados = resp.json()
    except ValueError:
        dados = {}

    return resp, dados


def main(argv: list[str] | None = None) -> int:
    code = _code_from_argv(argv)

    if not CLIENT_ID or not CLIENT_SECRET:
        print("Defina MAGALU_CLIENT_ID e MAGALU_CLIENT_SECRET no .env / ambiente.")
        return 1
    if not code:
        print("Informe o code: python pegar_token_magalu.py SEU_CODE (ou MAGALU_OAUTH_CODE).")
        return 1

    print("Enviando requisicao para o Magalu...")
    resp, dados = trocar_code_por_token(code)

    print(f"Status: {resp.status_code}")

    if "access_token" in dados:
        print("=" * 55)
        print("SUCESSO! Copie estes valores para o GitHub Secrets:")
        print("=" * 55)
        print(f"MAGALU_ACCESS_TOKEN:  {dados['access_token']}")
        print(f"MAGALU_REFRESH_TOKEN: {dados.get('refresh_token', '')}")
        print(f"Expira em:            {dados.get('expires_in', '?')} segundos")
        print("=" * 55)
        return 0

    print("ERRO:", dados)
    print("Dica: o code expira em 10 minutos — gere um novo e rode o script imediatamente.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
