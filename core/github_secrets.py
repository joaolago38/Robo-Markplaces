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
_aviso_gh_token = False
_probe_gravacao: dict = {"ok": None, "avisou": False}


def _pat_grava_secret() -> str:
    """PAT com secrets:write. O GITHUB_TOKEN padrão do Actions não grava Secret."""
    return (os.getenv("GH_TOKEN") or "").strip()


def reset_probe_gravacao_para_teste() -> None:
    _probe_gravacao["ok"] = None
    _probe_gravacao["avisou"] = False


def github_pode_gravar_secrets() -> bool:
    """Actions: PAT consegue GET da public-key de Secrets? Sem isso, não rotacione OAuth."""
    if _probe_gravacao["ok"] is not None:
        return bool(_probe_gravacao["ok"])

    if os.getenv("GITHUB_ACTIONS") != "true":
        _probe_gravacao["ok"] = True
        return True

    if not shutil.which("gh") or not _pat_grava_secret():
        _probe_gravacao["ok"] = False
        return False

    repo = (os.getenv("GH_REPO") or "").strip()
    if not repo:
        _probe_gravacao["ok"] = False
        return False

    try:
        subprocess.run(
            ["gh", "api", f"repos/{repo}/actions/secrets/public-key"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        _probe_gravacao["ok"] = True
        return True
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or str(e)).strip() or f"exit {e.returncode}"
        if not _probe_gravacao["avisou"]:
            logger.error(
                "GH_TOKEN não grava Secrets (public-key HTTP falhou): %s. "
                "Não rotacione ML/Magalu até o PAT ter secrets:write.",
                err[:400],
            )
            _probe_gravacao["avisou"] = True
        incrementar("token.sync_github_falha", tags=["motivo:gh_token_invalido"])
        _probe_gravacao["ok"] = False
        return False
    except Exception as exc:
        if not _probe_gravacao["avisou"]:
            logger.error("Não deu para checar se o PAT grava Secrets: %s", exc)
            _probe_gravacao["avisou"] = True
        _probe_gravacao["ok"] = False
        return False


def sync_secrets_github(
    access_token: str,
    refresh_token: str | None,
    prefix: str = "BLING",
    extras: dict | None = None,
) -> bool:
    """Atualiza {prefix}_ACCESS_TOKEN e opcionalmente {prefix}_REFRESH_TOKEN no GitHub."""
    if not shutil.which("gh"):
        logger.error("gh CLI não encontrado — Secret %s_* não atualizado", prefix)
        incrementar("token.sync_github_falha", tags=[f"prefix:{prefix}", "motivo:gh_ausente"])
        return False

    if os.getenv("GITHUB_ACTIONS") == "true" and not _pat_grava_secret():
        global _aviso_gh_token
        if not _aviso_gh_token:
            logger.warning(
                "Não gravou Secret %s_*: GH_TOKEN vazio. "
                "O GITHUB_TOKEN padrão do Actions não grava Secrets — "
                "defina secrets.GH_TOKEN (PAT com secrets:write) no workflow.",
                prefix,
            )
            _aviso_gh_token = True
        incrementar("token.sync_github_falha", tags=[f"prefix:{prefix}", "motivo:gh_token_vazio"])
        return False

    if not github_pode_gravar_secrets():
        incrementar("token.sync_github_falha", tags=[f"prefix:{prefix}", "motivo:gh_token_invalido"])
        return False

    repo = (os.getenv("GH_REPO") or "").strip()
    base_cmd = ["gh", "secret", "set"]
    repo_args = ["--repo", repo] if repo else []

    pares = [(f"{prefix}_ACCESS_TOKEN", access_token)]
    if refresh_token:
        pares.append((f"{prefix}_REFRESH_TOKEN", refresh_token))
    for nome, valor in (extras or {}).items():
        chave = str(nome or "").strip()
        dado = str(valor or "").strip()
        if chave and dado:
            pares.append((chave, dado))

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
