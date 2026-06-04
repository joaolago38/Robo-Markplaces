"""
pegar_token_ml.py
Troca o code OAuth2 pelo Access Token e Refresh Token do Mercado Livre (bootstrap).

Credenciais vêm de variáveis de ambiente / .env (NUNCA hardcoded):
    ML_CLIENT_ID, ML_CLIENT_SECRET
    ML_REDIRECT_URI   (opcional; default https://www.google.com)

Uso:
    1) Abra no navegador (autorize na conta ML):
       https://auth.mercadolivre.com.br/authorization?response_type=code&client_id=SEU_CLIENT_ID&redirect_uri=https://www.google.com
    2) Copie o "code" da URL de retorno (?code=XXXX) — expira em ~60s.
    3) Rode IMEDIATAMENTE, passando o code:
       python pegar_token_ml.py SEU_CODE
       (ou defina ML_OAUTH_CODE no ambiente)
"""
import os
import sys

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

CLIENT_ID = os.getenv("ML_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("ML_REDIRECT_URI", "https://www.google.com").strip()
CODE = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("ML_OAUTH_CODE", "")).strip()

if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("Defina ML_CLIENT_ID e ML_CLIENT_SECRET no .env / ambiente.")
if not CODE:
    sys.exit("Informe o code: python pegar_token_ml.py SEU_CODE (ou ML_OAUTH_CODE).")

print("Enviando requisicao para o ML...")
r = requests.post(
    "https://api.mercadolibre.com/oauth/token",
    headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
    data={
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": CODE,
        "redirect_uri": REDIRECT_URI,
    },
    timeout=15,
)

print(f"Status: {r.status_code}")
dados = r.json()

if "access_token" in dados:
    print("=" * 60)
    print("SUCESSO! Copie para o GitHub Secrets:")
    print("=" * 60)
    print(f"ML_ACCESS_TOKEN:  {dados['access_token']}")
    print(f"ML_REFRESH_TOKEN: {dados.get('refresh_token', '')}")
    print(f"ML_SELLER_ID:     {dados.get('user_id', '')}")
    print(f"Expira em:        {dados.get('expires_in', 0) // 3600}h")
    print("=" * 60)
else:
    print("ERRO:", dados)
    print("Dica: o code expira em 60s — gere um novo e rode imediatamente.")
