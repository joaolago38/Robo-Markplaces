"""
pegar_token_bling.py
Troca o code OAuth2 pelo Access Token e Refresh Token do Bling (bootstrap inicial).

Credenciais vêm de variáveis de ambiente / .env (NUNCA hardcoded):
    BLING_CLIENT_ID, BLING_CLIENT_SECRET
    BLING_REDIRECT_URI   (opcional; default https://google.com)

Uso:
    1) Abra no navegador (autorize na conta Bling):
       https://www.bling.com.br/Api/v3/oauth/authorize?response_type=code&client_id=SEU_CLIENT_ID&redirect_uri=https%3A%2F%2Fgoogle.com&state=robo
    2) Copie o "code" da URL de retorno (expira em ~60s).
    3) Rode IMEDIATAMENTE, passando o code:
       python pegar_token_bling.py SEU_CODE
       (ou defina BLING_OAUTH_CODE no ambiente)
"""
import base64
import os
import sys

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

CLIENT_ID = os.getenv("BLING_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("BLING_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("BLING_REDIRECT_URI", "https://google.com").strip()
CODE = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("BLING_OAUTH_CODE", "")).strip()

if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("Defina BLING_CLIENT_ID e BLING_CLIENT_SECRET no .env / ambiente.")
if not CODE:
    sys.exit("Informe o code: python pegar_token_bling.py SEU_CODE (ou BLING_OAUTH_CODE).")

credenciais = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

print("Enviando requisicao para o Bling...")
resp = requests.post(
    "https://www.bling.com.br/Api/v3/oauth/token",
    headers={
        "Authorization": f"Basic {credenciais}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    },
    data={"grant_type": "authorization_code", "code": CODE, "redirect_uri": REDIRECT_URI},
    timeout=15,
)

print(f"Status: {resp.status_code}")
dados = resp.json()

if "access_token" in dados:
    print("=" * 55)
    print("SUCESSO! Copie estes valores para o GitHub Secrets:")
    print("=" * 55)
    print(f"BLING_ACCESS_TOKEN:  {dados['access_token']}")
    print(f"BLING_REFRESH_TOKEN: {dados['refresh_token']}")
    print(f"Expira em:           {dados.get('expires_in', '?')} segundos")
    print("=" * 55)
else:
    print("ERRO:", dados)
    print("Dica: o code expira em 60s — gere um novo e rode o script imediatamente.")
