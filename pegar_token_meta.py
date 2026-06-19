"""
pegar_token_meta.py
Bootstrap OAuth2 do Meta (Facebook + Instagram Ads): troca o code pelo token
curto, estende para o token LONGO (~60 dias) e lista as contas de anúncio.

Credenciais vêm de variáveis de ambiente / .env (NUNCA hardcoded):
    META_APP_ID, META_APP_SECRET
    META_REDIRECT_URI   (opcional; default https://www.google.com)
    META_API_VERSION    (opcional; default v19.0)

Uso recomendado (sem copiar o code — evita expiração):
    1) No app Meta (developers.facebook.com), cadastre em OAuth Redirect URIs:
       http://127.0.0.1:8765/
    2) No .env: META_REDIRECT_URI=http://127.0.0.1:8765/
    3) Rode: python pegar_token_meta.py --listen
       (abre o navegador, captura o code e troca automaticamente)

Uso manual (code expira em ~1 minuto — cole IMEDIATAMENTE):
    python pegar_token_meta.py --url          # gera a URL
    python pegar_token_meta.py SEU_CODE       # troca o code
"""
from __future__ import annotations

import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, urlparse

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

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
CALLBACK_REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}/"


def url_autorizacao(
    scopes: str = "ads_read,business_management",
    redirect_uri: str | None = None,
) -> str:
    """Monta a URL do diálogo de autorização do Facebook."""
    ru = redirect_uri or REDIRECT_URI
    return (
        f"https://www.facebook.com/{API_VERSION}/dialog/oauth"
        f"?client_id={APP_ID}"
        f"&redirect_uri={quote(ru, safe='')}"
        f"&scope={scopes}"
        f"&response_type=code"
    )


def trocar_code_por_token(code: str, redirect_uri: str | None = None) -> dict:
    """Troca o code pelo token curto. Retorna o JSON da Graph API."""
    ru = redirect_uri or REDIRECT_URI
    r = requests.get(
        f"{BASE}/oauth/access_token",
        params={
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "redirect_uri": ru,
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


def capturar_code_callback(
    redirect_uri: str = CALLBACK_REDIRECT_URI,
    *,
    host: str = CALLBACK_HOST,
    port: int = CALLBACK_PORT,
    timeout: int = 180,
) -> str:
    """
    Sobe um servidor local, espera o redirect do Meta com ?code= e devolve o code.
  """
    esperado = redirect_uri.rstrip("/") + "/"
    resultado: dict[str, str] = {"code": ""}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            params = parse_qs(urlparse(self.path).query)
            resultado["code"] = (params.get("code") or [""])[0].strip()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Autorizado!</h2>"
                b"<p>Pode fechar esta aba e voltar ao terminal.</p></body></html>"
            )

        def log_message(self, _format, *_args):
            return

    server = HTTPServer((host, port), _Handler)
    server.timeout = 1

    elapsed = 0
    while elapsed < timeout and not resultado["code"]:
        server.handle_request()
        elapsed += 1

    server.server_close()
    if not resultado["code"]:
        raise TimeoutError(
            f"Nenhum code recebido em {timeout}s em {esperado} — autorize no navegador."
        )
    return resultado["code"]


def _processar_code(code: str, redirect_uri: str | None = None) -> int:
    print("Trocando code pelo token curto...")
    curto = trocar_code_por_token(code, redirect_uri=redirect_uri)
    short_token = curto.get("access_token")
    if not short_token:
        print("ERRO ao obter token curto:", curto)
        ru = redirect_uri or REDIRECT_URI
        print(f"redirect_uri usado: {ru}")
        print("Dica: o code expira em ~1 min e só vale uma vez.")
        print("      Use: python pegar_token_meta.py --listen  (captura automática)")
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


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    if not APP_ID or not APP_SECRET:
        print("Defina META_APP_ID e META_APP_SECRET no .env / ambiente.")
        return 1

    if argv and argv[0] in ("--url", "-u"):
        print("Abra esta URL no navegador, autorize e copie o 'code' da URL de retorno:")
        print(f"redirect_uri: {REDIRECT_URI}")
        print(url_autorizacao())
        print("\nO code expira em ~1 minuto. Para evitar copiar, use: python pegar_token_meta.py --listen")
        return 0

    if argv and argv[0] in ("--listen", "-l"):
        redirect = CALLBACK_REDIRECT_URI
        if REDIRECT_URI.rstrip("/") != redirect.rstrip("/"):
            print("AVISO: META_REDIRECT_URI no .env difere do modo --listen.")
            print(f"  .env atual:     {REDIRECT_URI}")
            print(f"  --listen usa:  {redirect}")
            print("  Cadastre o URI acima no app Meta e ajuste o .env, ou continue se já estiver OK.\n")

        auth_url = url_autorizacao(redirect_uri=redirect)
        print("Abrindo navegador para autorização...")
        print(f"redirect_uri: {redirect}")
        print(f"Se não abrir, cole no navegador:\n{auth_url}\n")
        print(f"Aguardando callback em {redirect} (até 3 min)...")
        try:
            webbrowser.open(auth_url)
            code = capturar_code_callback(redirect_uri=redirect)
        except TimeoutError as exc:
            print(f"ERRO: {exc}")
            return 1
        except OSError as exc:
            print(f"ERRO ao subir servidor local na porta {CALLBACK_PORT}: {exc}")
            return 1
        print("Code capturado — trocando imediatamente...")
        return _processar_code(code, redirect_uri=redirect)

    code = (argv[0] if argv else os.getenv("META_OAUTH_CODE", "")).strip()
    if not code:
        print("Informe o code: python pegar_token_meta.py SEU_CODE (ou META_OAUTH_CODE).")
        print("Recomendado (sem copiar): python pegar_token_meta.py --listen")
        print("URL manual:               python pegar_token_meta.py --url")
        return 1

    return _processar_code(code)


if __name__ == "__main__":
    raise SystemExit(main())
