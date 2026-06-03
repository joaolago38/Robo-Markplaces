#!/usr/bin/env python3
"""
scripts/debug_bling_refresh.py

Diagnóstico de uma tela: descobre POR QUE o refresh do Bling dá 400,
sem vazar os valores dos tokens no log.

Como rodar:
  Local:   .venv\\Scripts\\python.exe scripts\\debug_bling_refresh.py
  Linux:   python scripts/debug_bling_refresh.py

Precisa das envs: BLING_CLIENT_ID, BLING_CLIENT_SECRET, BLING_REFRESH_TOKEN
(carrega do .env automaticamente, se existir).
"""
import base64
import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

import requests

cid = os.getenv("BLING_CLIENT_ID", "")
sec = os.getenv("BLING_CLIENT_SECRET", "")
ref = os.getenv("BLING_REFRESH_TOKEN", "")


def _checa(nome, valor):
    problemas = []
    if not valor:
        problemas.append("VAZIO")
    if valor != valor.strip():
        problemas.append("tem espaço/quebra nas bordas")
    if valor.startswith("."):
        problemas.append("começa com '.' (defeito do .env.exemplo!)")
    if '"' in valor or "'" in valor:
        problemas.append("contém aspas")
    status = "OK" if not problemas else "; ".join(problemas)
    print(f"  {nome}: len={len(valor)}  -> {status}")


print("=" * 60)
print("DEBUG — refresh token do Bling")
print("=" * 60)
print("\n[1] Sanidade das credenciais (sem mostrar os valores):")
_checa("BLING_CLIENT_ID", cid)
_checa("BLING_CLIENT_SECRET", sec)
_checa("BLING_REFRESH_TOKEN", ref)

if not all([cid, sec, ref]):
    print("\n>>> Falta credencial. Configure as 3 envs e rode de novo.")
    sys.exit(1)

print("\n[2] Chamando POST /oauth/token (grant_type=refresh_token)...")
cred = base64.b64encode(f"{cid}:{sec}".encode()).decode()
r = requests.post(
    "https://www.bling.com.br/Api/v3/oauth/token",
    headers={
        "Authorization": f"Basic {cred}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    },
    data={"grant_type": "refresh_token", "refresh_token": ref},
    timeout=25,
)

print(f"  HTTP {r.status_code}")

if r.status_code == 200:
    print("  SUCESSO — o refresh funcionou! (NÃO vou imprimir os tokens no log)")
    print("  Pegue os novos tokens rodando a renovação normal e atualize os Secrets.")
    sys.exit(0)

# Em caso de erro, o corpo NÃO contém tokens válidos — seguro imprimir.
try:
    corpo = r.json()
except Exception:
    corpo = {}
erro = (corpo.get("error") or "").lower()
desc = corpo.get("error_description") or ""
print(f"  error        : {corpo.get('error')}")
print(f"  description  : {desc}")
print(f"  corpo bruto  : {r.text[:400]}")

print("\n[3] Veredito:")
if "invalid_grant" in erro or "grant" in (desc or "").lower():
    print("  >>> invalid_grant = refresh_token QUEIMADO/EXPIRADO.")
    print("      Conserto: rode pegar_token_bling.py, gere um par novo e")
    print("      atualize BLING_ACCESS_TOKEN e BLING_REFRESH_TOKEN nos Secrets.")
elif "invalid_client" in erro or "client" in (desc or "").lower():
    print("  >>> invalid_client = CLIENT_ID/CLIENT_SECRET errado.")
    print("      Conserto: corrija BLING_CLIENT_SECRET (e ID) — sem ponto, sem")
    print("      aspas, sem espaço — ANTES de tentar o pegar_token_bling.py.")
else:
    print("  >>> 400 sem 'error' claro. Veja o 'corpo bruto' acima.")
    print("      Quase sempre é refresh queimado OU client_secret errado.")

sys.exit(1)
