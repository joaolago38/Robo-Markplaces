import requests
import base64

# ─── CREDENCIAIS ───────────────────────────────────────────
CLIENT_ID     = "db6853620b6e2f6f259b1cb972f64bf5579bd4d0"
CLIENT_SECRET = "ae4b6c538688854cc04834e529bf1dd01fda8a8b683f12a8ba4d53d8c4d9"
REDIRECT_URI  = "https://google.com"

# ─── COLE O CODE AQUI ──────────────────────────────────────
# Gere em: https://www.bling.com.br/Api/v3/oauth/authorize?
#   response_type=code
#   &client_id=db6853620b6e2f6f259b1cb972f64bf5579bd4d0
#   &redirect_uri=https%3A%2F%2Fgoogle.com
#   &state=robo
CODE = "83ef3fd91e09ea5fe788f3e9d54d6ff920a019f1"
# ───────────────────────────────────────────────────────────

credenciais = base64.b64encode(
    f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
).decode()

print("Enviando requisicao para o Bling...")

resp = requests.post(
    "https://www.bling.com.br/Api/v3/oauth/token",
    headers={
        "Authorization": f"Basic {credenciais}",
        "Content-Type":  "application/x-www-form-urlencoded",
        "Accept":        "application/json",
    },
    data={
        "grant_type":   "authorization_code",
        "code":         CODE,
        "redirect_uri": REDIRECT_URI,
    },
    timeout=15
)

print(f"Status: {resp.status_code}")
dados = resp.json()

if "access_token" in dados:
    print()
    print("=" * 55)
    print("SUCESSO! Copie estes valores para o GitHub Secrets:")
    print("=" * 55)
    print(f"BLING_ACCESS_TOKEN:  {dados['access_token']}")
    print(f"BLING_REFRESH_TOKEN: {dados['refresh_token']}")
    print(f"Expira em:           {dados.get('expires_in', '?')} segundos")
    print("=" * 55)
else:
    print()
    print("ERRO:", dados)
    print()
    print("Dica: o code expira em 60s — gere um novo e rode o script imediatamente")