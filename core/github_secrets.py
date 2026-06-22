"""
core/github_secrets.py
Sincroniza tokens renovados nos Secrets do GitHub via gh CLI.
"""
from __future__ import annotations

import os
import shutil
import subprocess


def sync_secrets_github(
    access_token: str,
    refresh_token: str | None,
    prefix: str = "BLING",
) -> bool:
    """Atualiza {prefix}_ACCESS_TOKEN e opcionalmente {prefix}_REFRESH_TOKEN no GitHub."""
    if not shutil.which("gh"):
        print(f"  gh CLI não encontrado — Secret {prefix}_* não atualizado")
        return False

    repo = (os.getenv("GH_REPO") or "").strip()
    base_cmd = ["gh", "secret", "set"]
    repo_args = ["--repo", repo] if repo else []

    pares = [(f"{prefix}_ACCESS_TOKEN", access_token)]
    if refresh_token:
        pares.append((f"{prefix}_REFRESH_TOKEN", refresh_token))

    ok = True
    for nome, valor in pares:
        try:
            subprocess.run(
                base_cmd + [nome] + repo_args,
                input=valor,
                text=True,
                check=True,
                capture_output=True,
            )
            print(f"  Secret {nome} atualizado no GitHub")
        except subprocess.CalledProcessError as e:
            print(f"  Falha ao atualizar {nome}: {e.stderr.strip()}")
            ok = False
    return ok
