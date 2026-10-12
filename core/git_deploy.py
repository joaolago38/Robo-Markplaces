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


# ── Gestão de branches (limpeza + criar a partir da main) ──────────────────

def fetch_remote(
    *,
    remote: str = "origin",
    prune: bool = True,
    cwd: Path | None = None,
) -> dict[str, Any]:
    args = ["fetch", remote]
    if prune:
        args.append("--prune")
    r = _run_git(*args, cwd=cwd)
    return {
        "ok": r.returncode == 0,
        "remote": remote,
        "stdout": (r.stdout or "").strip(),
        "stderr": (r.stderr or "").strip() or None,
    }


def _normalizar_nome_branch_remota(ref: str, remote: str) -> str:
    nome = ref.strip().lstrip("* ").strip()
    prefixo = f"{remote}/"
    if nome.startswith(prefixo):
        return nome[len(prefixo) :]
    return nome


def listar_branches_remotas_mergeadas(
    *,
    base: str = "main",
    remote: str = "origin",
    cwd: Path | None = None,
) -> list[str]:
    ref_base = f"{remote}/{base}"
    r = _run_git("branch", "-r", "--merged", ref_base, cwd=cwd)
    if r.returncode != 0:
        return []
    resultado: list[str] = []
    vistos: set[str] = set()
    for linha in (r.stdout or "").splitlines():
        nome = _normalizar_nome_branch_remota(linha, remote)
        if not nome or "HEAD" in nome.upper() or nome == base:
            continue
        if nome not in vistos:
            vistos.add(nome)
            resultado.append(nome)
    return resultado


def listar_branches_locais_mergeadas(
    *,
    base: str = "main",
    cwd: Path | None = None,
) -> list[str]:
    r = _run_git("branch", "--merged", base, cwd=cwd)
    if r.returncode != 0:
        return []
    resultado: list[str] = []
    for linha in (r.stdout or "").splitlines():
        nome = linha.strip().lstrip("* ").strip()
        if not nome or nome == base:
            continue
        resultado.append(nome)
    return resultado


def _branch_elegivel_para_limpeza(
    nome: str,
    *,
    branch_atual: str,
    protegidas: frozenset[str],
    prefixos: tuple[str, ...],
) -> bool:
    if not nome or nome in protegidas:
        return False
    if nome == branch_atual:
        return False
    if prefixos:
        return any(nome.startswith(p) for p in prefixos)
    return True


def deletar_branch_remota(
    nome: str,
    *,
    remote: str = "origin",
    cwd: Path | None = None,
) -> dict[str, Any]:
    br = (nome or "").strip()
    if not br:
        return {"ok": False, "motivo": "nome da branch vazio"}
    r = _run_git("push", remote, "--delete", br, cwd=cwd)
    return {
        "ok": r.returncode == 0,
        "branch": br,
        "remote": remote,
        "stdout": (r.stdout or "").strip(),
        "stderr": (r.stderr or "").strip() or None,
    }


def deletar_branch_local(
    nome: str,
    *,
    cwd: Path | None = None,
) -> dict[str, Any]:
    br = (nome or "").strip()
    if not br:
        return {"ok": False, "motivo": "nome da branch vazio"}
    r = _run_git("branch", "-d", br, cwd=cwd)
    return {
        "ok": r.returncode == 0,
        "branch": br,
        "stdout": (r.stdout or "").strip(),
        "stderr": (r.stderr or "").strip() or None,
    }


def criar_branch_de_main(
    nome: str,
    *,
    base: str = "main",
    remote: str = "origin",
    push_upstream: bool = False,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """
    Atualiza a main remota e cria (ou faz checkout em) uma branch nova a partir dela.
    """
    br = (nome or "").strip()
    if not br:
        return {"ok": False, "motivo": "nome da branch vazio"}

    status = obter_status(cwd=cwd)
    if status.get("tem_alteracoes"):
        return {
            "ok": False,
            "etapa": "status",
            "motivo": "há alterações locais não commitadas; faça commit ou stash antes",
            "alteracoes": status.get("total_alteracoes"),
        }

    fetch = fetch_remote(remote=remote, prune=True, cwd=cwd)
    if not fetch.get("ok"):
        return {"ok": False, "etapa": "fetch", "erro": fetch.get("stderr")}

    r_base = _run_git("checkout", base, cwd=cwd)
    if r_base.returncode != 0:
        r_base = _run_git("checkout", "-B", base, f"{remote}/{base}", cwd=cwd)
    if r_base.returncode != 0:
        return {"ok": False, "etapa": "checkout_base", "erro": (r_base.stderr or "").strip()}

    pull = _run_git("pull", "--ff-only", remote, base, cwd=cwd)
    if pull.returncode != 0:
        logger.warning("git_deploy: pull %s/%s falhou (continuando): %s", remote, base, pull.stderr)

    r_existe = _run_git("rev-parse", "--verify", br, cwd=cwd)
    if r_existe.returncode == 0:
        r_chk = _run_git("checkout", br, cwd=cwd)
        return {
            "ok": r_chk.returncode == 0,
            "branch": br,
            "base": base,
            "criada": False,
            "checkout": True,
            "stderr": (r_chk.stderr or "").strip() or None,
        }

    r_nova = _run_git("checkout", "-b", br, cwd=cwd)
    if r_nova.returncode != 0:
        return {"ok": False, "etapa": "checkout_nova", "erro": (r_nova.stderr or "").strip()}

    resultado: dict[str, Any] = {
        "ok": True,
        "branch": br,
        "base": base,
        "criada": True,
        "push_enviado": False,
    }

    if push_upstream:
        push_res = push(remote=remote, branch=br, cwd=cwd)
        resultado["push_enviado"] = bool(push_res.get("ok"))
        if not push_res.get("ok"):
            resultado["ok"] = False
            resultado["etapa"] = "push"
            resultado["erro"] = push_res.get("stderr")
    return resultado


def executar_limpeza_branches(
    *,
    base: str = "main",
    remote: str = "origin",
    protegidas: frozenset[str] | None = None,
    prefixos: tuple[str, ...] = (),
    limpar_remotas: bool = True,
    limpar_locais: bool = True,
    dry_run: bool = False,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """
    Remove branches já mergeadas na base (local e/ou remoto).
    Nunca usa force push nem deleta a branch atual ou protegidas.
    """
    protegidas = protegidas or frozenset({base, "master"})
    branch_atual = obter_branch_atual(cwd=cwd)

    fetch = fetch_remote(remote=remote, prune=True, cwd=cwd)
    if not fetch.get("ok"):
        return {"ok": False, "etapa": "fetch", "erro": fetch.get("stderr")}

    candidatas_remotas = listar_branches_remotas_mergeadas(base=base, remote=remote, cwd=cwd)
    candidatas_locais = listar_branches_locais_mergeadas(base=base, cwd=cwd) if limpar_locais else []

    elegiveis_remotas = [
        b
        for b in candidatas_remotas
        if _branch_elegivel_para_limpeza(
            b, branch_atual=branch_atual, protegidas=protegidas, prefixos=prefixos
        )
    ]
    elegiveis_locais = [
        b
        for b in candidatas_locais
        if _branch_elegivel_para_limpeza(
            b, branch_atual=branch_atual, protegidas=protegidas, prefixos=prefixos
        )
    ]

    resultado: dict[str, Any] = {
        "ok": True,
        "base": base,
        "branch_atual": branch_atual,
        "dry_run": dry_run,
        "remotas_candidatas": candidatas_remotas,
        "locais_candidatas": candidatas_locais,
        "remotas_deletadas": [],
        "locais_deletadas": [],
        "remotas_falhas": [],
        "locais_falhas": [],
    }

    if dry_run:
        resultado["remotas_planejadas"] = elegiveis_remotas
        resultado["locais_planejadas"] = elegiveis_locais
        resultado["motivo"] = "dry_run: nenhuma branch deletada"
        return resultado

    if limpar_remotas:
        for br in elegiveis_remotas:
            del_res = deletar_branch_remota(br, remote=remote, cwd=cwd)
            if del_res.get("ok"):
                resultado["remotas_deletadas"].append(br)
            else:
                resultado["remotas_falhas"].append({"branch": br, "erro": del_res.get("stderr")})

    if limpar_locais:
        for br in elegiveis_locais:
            del_res = deletar_branch_local(br, cwd=cwd)
            if del_res.get("ok"):
                resultado["locais_deletadas"].append(br)
            else:
                resultado["locais_falhas"].append({"branch": br, "erro": del_res.get("stderr")})

    if resultado["remotas_falhas"] or resultado["locais_falhas"]:
        resultado["ok"] = False

    return resultado
