"""
pegar_token_amazon.py
Troca o code OAuth2 pelo Access Token e Refresh Token da Amazon SP-API (bootstrap inicial),
usando o fluxo Login with Amazon (LWA).

Credenciais vêm de variáveis de ambiente / .env (NUNCA hardcoded):
    AMAZON_LWA_CLIENT_ID, AMAZON_LWA_CLIENT_SECRET
    AMAZON_REDIRECT_URI   (opcional; default https://www.google.com)

Como gerar o "code":
    1) No Seller Central, crie um app privado SP-API:
       Apps e Serviços → Desenvolver Apps → Adicionar novo app cliente SP-API.
       Anote o LWA Client ID e Client Secret e defina a Redirect URI
       (use https://www.google.com se não tiver um site próprio).
    2) Autorize o app na sua própria conta (self-authorization), na tela final
       do cadastro do app privado. A Amazon vai redirecionar para a Redirect URI.
    3) Copie o "code" (parâmetro ?spapi_oauth_code=XXXX ou ?code=XXXX) da URL de
       retorno. ATENÇÃO: o code expira em poucos minutos.
    4) Rode IMEDIATAMENTE, passando o code:
       python pegar_token_amazon.py SEU_CODE
       (ou defina AMAZON_OAUTH_CODE no ambiente)
"""
from __future__ import annotations

import os
import sys

import requests

TOKEN_URL = "https://api.amazon.com/auth/o2/token"


def _carregar_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass


_carregar_dotenv()

CLIENT_ID = os.getenv("AMAZON_LWA_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("AMAZON_LWA_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("AMAZON_REDIRECT_URI", "https://www.google.com").strip()


def _code_from_argv(argv: list[str] | None) -> str:
    args = argv if argv is not None else sys.argv[1:]
    if args:
        return args[0].strip()
    return os.getenv("AMAZON_OAUTH_CODE", "").strip()


def trocar_code_por_token(code: str) -> tuple[requests.Response, dict]:
    """Troca authorization_code por access_token + refresh_token (LWA)."""
    resp = requests.post(
        TOKEN_URL,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
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
        print("Defina AMAZON_LWA_CLIENT_ID e AMAZON_LWA_CLIENT_SECRET no .env / ambiente.")
        return 1
    if not code:
        print("Informe o code: python pegar_token_amazon.py SEU_CODE (ou AMAZON_OAUTH_CODE).")
        return 1

    print("Enviando requisicao para a Amazon (LWA)...")
    resp, dados = trocar_code_por_token(code)

    print(f"Status: {resp.status_code}")

    if "access_token" in dados:
        print("=" * 60)
        print("SUCESSO! Copie para o GitHub Secrets:")
        print("=" * 60)
        print(f"AMAZON_ACCESS_TOKEN:  {dados['access_token']}")
        print(f"AMAZON_REFRESH_TOKEN: {dados.get('refresh_token', '')}")
        expires = dados.get("expires_in", 0)
        try:
            horas = int(expires) // 3600
        except (TypeError, ValueError):
            horas = 0
        print(f"Expira em:            {horas}h")
        print("=" * 60)
        print()
        print("AINDA FALTA definir manualmente (nao vem nesta resposta):")
        print("  AMAZON_SELLER_ID      -> Merchant Token, em Seller Central:")
        print("                           Configuracoes da conta -> Informacoes comerciais")
        print("  AMAZON_MARKETPLACE_ID -> Brasil = A2Q3Y263D00KWC (valor fixo)")
        return 0

    print("ERRO:", dados)
    print("Dica: o code OAuth expira rapido — gere um novo no Seller Central e rode imediatamente.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
