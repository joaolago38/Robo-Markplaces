"""
core/github_secrets.py
Sincroniza tokens renovados nos Secrets do GitHub via gh CLI.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

from core.datadog_metrics import incrementar

logger = logging.getLogger("github_secrets")


def _pat_grava_secret() -> str:
    """PAT com secrets:write. O GITHUB_TOKEN padrão do Actions não grava Secret."""
    return (os.getenv("GH_TOKEN") or "").strip()


def sync_secrets_github(
    access_token: str,
    refresh_token: str | None,
    prefix: str = "BLING",
) -> bool:
    """Atualiza {prefix}_ACCESS_TOKEN e opcionalmente {prefix}_REFRESH_TOKEN no GitHub."""
    if not shutil.which("gh"):
        logger.error("gh CLI não encontrado — Secret %s_* não atualizado", prefix)
        incrementar("token.sync_github_falha", tags=[f"prefix:{prefix}", "motivo:gh_ausente"])
        return False

    if os.getenv("GITHUB_ACTIONS") == "true" and not _pat_grava_secret():
        logger.error(
            "Não gravou Secret %s_*: GH_TOKEN vazio. "
            "O GITHUB_TOKEN padrão do Actions não grava Secrets — "
            "defina secrets.GH_TOKEN (PAT com secrets:write) no workflow.",
            prefix,
        )
        incrementar("token.sync_github_falha", tags=[f"prefix:{prefix}", "motivo:gh_token_vazio"])
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
            logger.info("Secret %s atualizado no GitHub", nome)
        except subprocess.CalledProcessError as e:
            err = (e.stderr or e.stdout or str(e)).strip() or f"exit {e.returncode}"
            logger.error("Falha ao atualizar %s no GitHub: %s", nome, err)
            incrementar(
                "token.sync_github_falha",
                tags=[f"prefix:{prefix}", "motivo:gh_secret_set"],
            )
            ok = False
    return ok
