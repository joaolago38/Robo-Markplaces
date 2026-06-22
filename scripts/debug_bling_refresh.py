#!/usr/bin/env python3
"""
scripts/debug_bling_refresh.py

Diagnóstico do refresh do Bling (erros 400) e, em caso de SUCESSO,
sincroniza ou exibe os novos tokens — o Bling rotaciona o refresh_token
a cada renovação e o valor antigo é invalidado imediatamente.

Como rodar:
  Local:   .venv\\Scripts\\python.exe scripts\\debug_bling_refresh.py
  Linux:   python scripts/debug_bling_refresh.py

Precisa das envs: BLING_CLIENT_ID, BLING_CLIENT_SECRET, BLING_REFRESH_TOKEN
(carrega do .env automaticamente, se existir).

Em GitHub Actions (GITHUB_ACTIONS=true), tenta atualizar os Secrets via gh CLI.
Fora do Actions ou se o sync falhar, imprime os tokens para cópia manual.
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from core.github_secrets import sync_secrets_github

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

cid = os.getenv("BLING_CLIENT_ID", "")
sec = os.getenv("BLING_CLIENT_SECRET", "")
ref = os.getenv("BLING_REFRESH_TOKEN", "")


def _checa(nome: str, valor: str) -> None:
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


def _imprimir_tokens_fallback(access_token: str, refresh_token: str | None) -> None:
    print("=" * 60)
    print("SUCESSO! O refresh funcionou e o token foi ROTACIONADO.")
    print("Copie AGORA estes valores para os Secrets do GitHub, ou a")
    print("proxima renovacao automatica vai falhar (token antigo invalidado):")
    print("=" * 60)
    print(f"BLING_ACCESS_TOKEN:  {access_token}")
    print(f"BLING_REFRESH_TOKEN: {refresh_token or ''}")
    print("=" * 60)


def _handle_refresh_success(access_token: str, refresh_token: str | None) -> int:
    """Persiste tokens novos no GitHub ou exibe para cópia manual."""
    if not access_token:
        print("  SUCESSO HTTP 200, mas access_token ausente na resposta JSON.")
        return 1

    em_actions = os.getenv("GITHUB_ACTIONS") == "true"
    if em_actions:
        if sync_secrets_github(access_token, refresh_token, prefix="BLING"):
            print("  SUCESSO — refresh OK. Secrets BLING_* atualizados no GitHub.")
            return 0
        print("  SUCESSO — refresh OK, mas sync dos Secrets falhou.")
        print("  Copie os tokens abaixo para não perder o refresh rotacionado:")

    _imprimir_tokens_fallback(access_token, refresh_token)
    return 0


def _diagnosticar_erro_refresh(resposta: requests.Response) -> int:
    try:
        corpo = resposta.json()
    except Exception:
        corpo = {}
    erro = (corpo.get("error") or "").lower()
    desc = corpo.get("error_description") or ""
    print(f"  error        : {corpo.get('error')}")
    print(f"  description  : {desc}")
    print(f"  corpo bruto  : {resposta.text[:400]}")

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

    return 1


def main() -> int:
    print("=" * 60)
    print("DEBUG — refresh token do Bling")
    print("=" * 60)
    print("\n[1] Sanidade das credenciais (sem mostrar os valores):")
    _checa("BLING_CLIENT_ID", cid)
    _checa("BLING_CLIENT_SECRET", sec)
    _checa("BLING_REFRESH_TOKEN", ref)

    if not all([cid, sec, ref]):
        print("\n>>> Falta credencial. Configure as 3 envs e rode de novo.")
        return 1

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
        dados = r.json() if r.content else {}
        return _handle_refresh_success(
            str(dados.get("access_token") or ""),
            dados.get("refresh_token"),
        )

    return _diagnosticar_erro_refresh(r)


if __name__ == "__main__":
    raise SystemExit(main())
