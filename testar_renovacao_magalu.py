"""
testar_renovacao_magalu.py
Chama diretamente o endpoint de refresh do Magalu (bypassa qualquer
cache em memória/disco) e mostra a resposta HTTP crua — pra saber se
o MAGALU_REFRESH_TOKEN ainda é válido, e se existe algum arquivo de
cache (MAGALU_TOKEN_STORE) atrapalhando.

Uso:
    python testar_renovacao_magalu.py

Não imprime nenhum token, só status/erros.
"""
from __future__ import annotations

import os
import time
import urllib.parse

from dotenv import load_dotenv

load_dotenv()

from pathlib import Path  # noqa: E402

import requests  # noqa: E402


def checar_store_em_disco() -> None:
    caminho = os.getenv("MAGALU_TOKEN_STORE")
    print(f"MAGALU_TOKEN_STORE (env) = {caminho!r}")
    if caminho:
        p = Path(caminho)
        print(f"Arquivo existe? {p.exists()}")
        if p.exists():
            print(f"Modificado em: {time.ctime(p.stat().st_mtime)}")
            print("-> Se esse arquivo for antigo, pode estar entregando um")
            print("   access_token expirado achando que ainda é válido.")
    print()


def testar_refresh_direto() -> None:
    client_id = os.getenv("MAGALU_CLIENT_ID", "").strip()
    client_secret = os.getenv("MAGALU_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("MAGALU_REFRESH_TOKEN", "").strip()

    print(f"MAGALU_CLIENT_ID definido? {bool(client_id)}")
    print(f"MAGALU_CLIENT_SECRET definido? {bool(client_secret)}")
    print(f"MAGALU_REFRESH_TOKEN definido? {bool(refresh_token)}")
    print()

    if not all([client_id, client_secret, refresh_token]):
        print("Faltam credenciais no .env — não dá pra testar.")
        return

    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }
    )

    print("Chamando POST https://id.magalu.com/oauth/token diretamente...")
    r = requests.post(
        "https://id.magalu.com/oauth/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=25,
    )
    print(f"status={r.status_code}")
    print(f"body={r.text[:500]}")
    print()

    if r.status_code == 200:
        print("SUCESSO — o refresh_token ainda é válido.")
        print("(Se ainda assim o probe_conexao/testar_hosts deu 401, o cache")
        print(" em disco ou em memória é o problema, não a credencial.)")
    else:
        print("FALHOU — o refresh_token está inválido/expirado/revogado.")
        print("Solução: gerar um novo 'code' de autorização no ID Magalu e")
        print("rodar 'python pegar_token_magalu.py NOVO_CODE' de novo.")


def main() -> None:
    checar_store_em_disco()
    testar_refresh_direto()


if __name__ == "__main__":
    main()
