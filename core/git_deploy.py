"""
core/git_deploy.py
Operações git seguras para deploy local (sem force push, sem secrets).
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("git_deploy")

_PATHS_NUNCA_COMMITAR = (
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "secrets.json",
    "*.pem",
    "*.key",
    "id_rsa",
)


def _run_git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["git", *args]
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def obter_branch_atual(*, cwd: Path | None = None) -> str:
    r = _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()


def obter_status(*, cwd: Path | None = None) -> dict[str, Any]:
    r = _run_git("status", "--porcelain", cwd=cwd)
    linhas = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    return {
        "ok": r.returncode == 0,
        "branch": obter_branch_atual(cwd=cwd),
        "alteracoes": linhas,
        "total_alteracoes": len(linhas),
        "tem_alteracoes": bool(linhas),
        "stderr": (r.stderr or "").strip() or None,
    }


def _deve_ignorar_arquivo(caminho: str) -> bool:
    nome = caminho.replace("\\", "/").strip()
    if nome.startswith("??"):
        nome = nome[2:].strip()
    elif len(nome) > 2 and nome[1] == " ":
        nome = nome[3:].strip()
    base = Path(nome).name.lower()
    for padrao in _PATHS_NUNCA_COMMITAR:
        if padrao.startswith("*") and base.endswith(padrao[1:]):
            return True
        if base == padrao.lower():
            return True
    return False


def listar_arquivos_para_stage(
  status: dict[str, Any],
  *,
  paths_excluir: tuple[str, ...] = (),
) -> list[str]:
    excluir = {p.replace("\\", "/").rstrip("/") for p in paths_excluir}
    resultado: list[str] = []
    for linha in status.get("alteracoes") or []:
        if len(linha) < 4:
            continue
        caminho = linha[3:].strip().replace("\\", "/")
        if _deve_ignorar_arquivo(caminho):
            logger.warning("git_deploy: ignorando arquivo sensível %s", caminho)
            continue
        if any(caminho == e or caminho.startswith(e + "/") for e in excluir):
            continue
        resultado.append(caminho)
    return resultado


def adicionar_arquivos(caminhos: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    if not caminhos:
        return {"ok": True, "adicionados": 0}
    r = _run_git("add", "--", *caminhos, cwd=cwd)
    return {
        "ok": r.returncode == 0,
        "adicionados": len(caminhos),
        "stderr": (r.stderr or "").strip() or None,
    }


def criar_commit(mensagem: str, *, cwd: Path | None = None) -> dict[str, Any]:
    msg = (mensagem or "").strip()
    if not msg:
        return {"ok": False, "motivo": "mensagem de commit vazia"}
    r = _run_git("commit", "-m", msg, cwd=cwd)
    return {
        "ok": r.returncode == 0,
        "stdout": (r.stdout or "").strip(),
        "stderr": (r.stderr or "").strip() or None,
    }


def push(
    *,
    remote: str = "origin",
    branch: str | None = None,
    cwd: Path | None = None,
    set_upstream: bool = True,
) -> dict[str, Any]:
    br = branch or obter_branch_atual(cwd=cwd)
    if not br:
        return {"ok": False, "motivo": "branch não detectada"}
    args = ["push"]
    if set_upstream:
        args.extend(["-u", remote, br])
    else:
        args.extend([remote, br])
    r = _run_git(*args, cwd=cwd)
    return {
        "ok": r.returncode == 0,
        "branch": br,
        "remote": remote,
        "stdout": (r.stdout or "").strip(),
        "stderr": (r.stderr or "").strip() or None,
    }


def executar_push_deploy_git(
    *,
    mensagem_commit: str,
    branch: str | None = None,
    remote: str = "origin",
    dry_run: bool = False,
    paths_excluir: tuple[str, ...] = (),
    cwd: Path | None = None,
) -> dict[str, Any]:
    """
  Status → add (seguro) → commit → push. Nunca usa --force.
    """
    status = obter_status(cwd=cwd)
    if not status.get("ok"):
        return {"ok": False, "etapa": "status", "erro": status.get("stderr") or "git status falhou"}

    arquivos = listar_arquivos_para_stage(status, paths_excluir=paths_excluir)
    resultado: dict[str, Any] = {
        "ok": True,
        "branch": status.get("branch"),
        "total_alteracoes": status.get("total_alteracoes"),
        "arquivos_stage": arquivos,
        "commit_criado": False,
        "push_enviado": False,
        "dry_run": dry_run,
    }

    if not arquivos:
        resultado["motivo"] = "nenhuma alteração para commitar"
        return resultado

    if dry_run:
        resultado["motivo"] = "dry_run: commit/push não executados"
        return resultado

    add = adicionar_arquivos(arquivos, cwd=cwd)
    if not add.get("ok"):
        return {**resultado, "ok": False, "etapa": "add", "erro": add.get("stderr")}

    commit = criar_commit(mensagem_commit, cwd=cwd)
    if not commit.get("ok"):
        return {**resultado, "ok": False, "etapa": "commit", "erro": commit.get("stderr")}
    resultado["commit_criado"] = True

    br = branch or status.get("branch") or ""
    push_res = push(remote=remote, branch=br, cwd=cwd)
    if not push_res.get("ok"):
        return {**resultado, "ok": False, "etapa": "push", "erro": push_res.get("stderr")}
    resultado["push_enviado"] = True
    return resultado
