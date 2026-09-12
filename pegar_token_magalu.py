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

import base64
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

import requests

_ROOT = Path(__file__).resolve().parent


def _carregar_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(_ROOT / ".env")
        load_dotenv()
    except Exception:
        pass


_carregar_dotenv()

TOKEN_URL = "https://id.magalu.com/oauth/token"
AUTHORIZE_URL = "https://id.magalu.com/login"

CLIENT_ID = os.getenv("MAGALU_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("MAGALU_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("MAGALU_REDIRECT_URI", "https://www.google.com").strip()


def url_autorizacao() -> str:
    """URL de consentimento (o portal também gera uma com os escopos do app)."""
    qs = urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
        }
    )
    return f"{AUTHORIZE_URL}?{qs}"


def _imprimir_como_obter_code() -> None:
    print("Falta o code OAuth — o portal ainda está em 'Aguardando autorização'.")
    print()
    print("1) No developers.magalu.com, na aplicação, clique em Copiar URL de autorização")
    print("   (é o jeito mais seguro: já vai com os escopos do app).")
    print("   Fallback se o botão falhar:")
    if CLIENT_ID:
        print(f"   {url_autorizacao()}")
    print("2) Cole no navegador, entre com a CONTA DA LOJA Magalu e autorize.")
    print(f"3) Vai cair em {REDIRECT_URI}?code=XXXX — copie só o XXXX (antes de &).")
    print("4) Rode IMEDIATAMENTE (o code dura poucos minutos):")
    print("   python pegar_token_magalu.py COLE_O_CODE_AQUI")
    print()
    print("Não cole o Client Secret nem os tokens no chat. Só o code da URL.")


def _code_from_argv(argv: list[str] | None) -> str:
    args = argv if argv is not None else sys.argv[1:]
    if args:
        return args[0].strip()
    return os.getenv("MAGALU_OAUTH_CODE", "").strip()


def _basic_auth_header() -> str:
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _parse_json(resp: requests.Response) -> dict:
    try:
        dados = resp.json()
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def trocar_code_por_token(code: str) -> tuple[requests.Response, dict]:
    """
    Troca authorization_code por tokens.

    A doc do Magalu usa JSON com client_id/secret no corpo. O ID Magalu
    também aceita form-urlencoded e HTTP Basic. 401 invalid_client no
    primeiro formato não prova que o client está errado — tenta os três.
    """
    body = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }
    tentativas = [
        {
            "json": body,
            "headers": {"Content-Type": "application/json"},
        },
        {
            "data": body,
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        },
        {
            "data": {
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
                "code": code,
            },
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": _basic_auth_header(),
            },
        },
    ]

    resp = None
    dados: dict = {}
    for kwargs in tentativas:
        resp = requests.post(TOKEN_URL, timeout=15, **kwargs)
        dados = _parse_json(resp)
        if resp.status_code < 400 or "access_token" in dados:
            return resp, dados
        if resp.status_code not in (400, 401, 415):
            return resp, dados

    assert resp is not None
    return resp, dados


def main(argv: list[str] | None = None) -> int:
    code = _code_from_argv(argv)

    if not CLIENT_ID or not CLIENT_SECRET:
        print("Defina MAGALU_CLIENT_ID e MAGALU_CLIENT_SECRET no .env / ambiente.")
        return 1
    if not code:
        _imprimir_como_obter_code()
        return 1

    print("Enviando requisicao para o Magalu...")
    print(f"Client ID (mascarado): {CLIENT_ID[:4]}...{CLIENT_ID[-4:]} (tam={len(CLIENT_ID)})")
    print(f"Redirect: {REDIRECT_URI}")
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
    print("Dica: o code vale uma vez só e dura ~10 min — abra a URL de login de novo.")
    if dados.get("error") == "invalid_client":
        print("invalid_client = ID/secret/método. Confira MAGALU_CLIENT_ID no .env")
        print("(tem que ser o mesmo da URL de autorização, sem 3 extra no começo).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
