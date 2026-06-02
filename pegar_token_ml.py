"""
pegar_token_ml.py
Troca o code OAuth2 pelo Access Token e Refresh Token do ML.

Uso:
    1. Abra no navegador:
       https://auth.mercadolivre.com.br/authorization?response_type=code&client_id=7869766083120381&redirect_uri=https://www.google.com.br

    2. Autorize → copie o code da URL do Google (?code=XXXXX)

    3. Cole o code abaixo e rode IMEDIATAMENTE (expira em 60s):
       .venv\\Scripts\\python.exe pegar_token_ml.py
"""
import requests

CLIENT_ID     = "7869766083120381"
CLIENT_SECRET = "wVDAVJnt2DH5qkoWWt2if0vUP8D1yUJs"
REDIRECT_URI  = "https://www.google.com"

# ── COLE O CODE AQUI ──────────────────────────────────────────
CODE = "TG-6a1f3a2510d5e40001c2a90b-1651424153"
# ──────────────────────────────────────────────────────────────

print("Enviando requisição para o ML...")

r = requests.post(
    "https://api.mercadolibre.com/oauth/token",
    headers={
        "Accept":       "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    },
    data={
        "grant_type":    "authorization_code",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code":          CODE,
        "redirect_uri":  REDIRECT_URI,
    },
    timeout=15,
)

print(f"Status: {r.status_code}")
dados = r.json()

if "access_token" in dados:
    print()
    print("=" * 60)
    print("SUCESSO! Copie para o GitHub Secrets:")
    print("=" * 60)
    print(f"ML_CLIENT_ID:     {CLIENT_ID}")
    print(f"ML_CLIENT_SECRET: {CLIENT_SECRET}")
    print(f"ML_ACCESS_TOKEN:  {dados['access_token']}")
    print(f"ML_REFRESH_TOKEN: {dados.get('refresh_token', '')}")
    print(f"ML_SELLER_ID:     {dados.get('user_id', '1651424153')}")
    print(f"Expira em:        {dados.get('expires_in', 0) // 3600}h")
    print("=" * 60)
else:
    print("ERRO:", dados)
    print()
    print("Dica: o code expira em 60s — gere um novo e rode imediatamente")
