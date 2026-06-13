"""
pegar_token_meta.py
Bootstrap OAuth2 do Meta (Facebook + Instagram Ads): troca o code pelo token
curto, estende para o token LONGO (~60 dias) e lista as contas de anúncio.

Credenciais vêm de variáveis de ambiente / .env (NUNCA hardcoded):
    META_APP_ID, META_APP_SECRET
    META_REDIRECT_URI   (opcional; default https://www.google.com)
    META_API_VERSION    (opcional; default v19.0)

Uso:
    1) Abra a URL de autorização (impressa por --url) no navegador, logado na
       conta com acesso ao Gerenciador de Anúncios, e autorize.
       Permissões necessárias: ads_read (ler desempenho), business_management.
    2) Copie o "code" da URL de retorno (?code=XXXX) — expira rápido.
    3) Rode IMEDIATAMENTE, passando o code:
       python pegar_token_meta.py SEU_CODE
       (ou defina META_OAUTH_CODE no ambiente)

Apenas mostrar a URL de autorização:
    python pegar_token_meta.py --url
"""
import os
import sys

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

APP_ID = os.getenv("META_APP_ID", "").strip()
APP_SECRET = os.getenv("META_APP_SECRET", "").strip()
REDIRECT_URI = os.getenv("META_REDIRECT_URI", "https://www.google.com").strip()
API_VERSION = os.getenv("META_API_VERSION", "v19.0").strip()
BASE = f"https://graph.facebook.com/{API_VERSION}"


def url_autorizacao(scopes: str = "ads_read,business_management") -> str:
    """Monta a URL do diálogo de autorização do Facebook."""
    return (
        f"https://www.facebook.com/{API_VERSION}/dialog/oauth"
        f"?client_id={APP_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={scopes}"
        f"&response_type=code"
    )


def trocar_code_por_token(code: str) -> dict:
    """Troca o code pelo token curto. Retorna o JSON da Graph API."""
    r = requests.get(
        f"{BASE}/oauth/access_token",
        params={
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        timeout=15,
    )
    return r.json()


def trocar_por_longa_duracao(short_token: str) -> dict:
    """Estende o token curto para o token longo (~60 dias)."""
    r = requests.get(
        f"{BASE}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "fb_exchange_token": short_token,
        },
        timeout=15,
    )
    return r.json()


def listar_contas_anuncio(token: str) -> list[dict]:
    """Lista as contas de anúncio acessíveis pelo token (id + nome)."""
    try:
        r = requests.get(
            f"{BASE}/me/adaccounts",
            params={"access_token": token, "fields": "name,account_id,currency"},
            timeout=15,
        )
        return r.json().get("data", [])
    except Exception as exc:
        print(f"  (não foi possível listar contas: {exc})")
        return []


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    if not APP_ID or not APP_SECRET:
        print("Defina META_APP_ID e META_APP_SECRET no .env / ambiente.")
        return 1

    if argv and argv[0] in ("--url", "-u"):
        print("Abra esta URL no navegador, autorize e copie o 'code' da URL de retorno:")
        print(url_autorizacao())
        return 0

    code = (argv[0] if argv else os.getenv("META_OAUTH_CODE", "")).strip()
    if not code:
        print("Informe o code: python pegar_token_meta.py SEU_CODE (ou META_OAUTH_CODE).")
        print("Para gerar a URL de autorização: python pegar_token_meta.py --url")
        return 1

    print("Trocando code pelo token curto...")
    curto = trocar_code_por_token(code)
    short_token = curto.get("access_token")
    if not short_token:
        print("ERRO ao obter token curto:", curto)
        print("Dica: o code expira rápido — gere um novo (--url) e rode imediatamente.")
        return 1

    print("Estendendo para o token longo (~60 dias)...")
    longo = trocar_por_longa_duracao(short_token)
    long_token = longo.get("access_token")
    if not long_token:
        print("ERRO ao obter token longo:", longo)
        return 1

    print("=" * 60)
    print("SUCESSO! Copie para os GitHub Secrets / .env:")
    print("=" * 60)
    print(f"META_ACCESS_TOKEN: {long_token}")
    print(f"Expira em (s):     {longo.get('expires_in', '?')}")

    contas = listar_contas_anuncio(long_token)
    if contas:
        print("\nContas de anúncio disponíveis (use uma em META_AD_ACCOUNT_ID):")
        for c in contas:
            print(f"  act_{c.get('account_id')}  —  {c.get('name')} ({c.get('currency', '')})")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
