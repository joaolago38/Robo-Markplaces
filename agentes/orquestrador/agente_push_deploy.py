"""
agentes/orquestrador/agente_push_deploy.py
Faz push seguro no repositório e executa todos os agentes (sync completo).

Uso local:
  python -m agentes.orquestrador.agente_push_deploy
  python -m agentes.orquestrador.agente_push_deploy --sem-push
  python -m agentes.orquestrador.agente_push_deploy --mensagem "feat: ajustes"

Após o push local, o sync na nuvem (`push_main_rotinas.yml`) só roda se você
disparar manualmente no Actions (não dispara mais após CI).
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from typing import Any

from agentes.orquestrador.agente_git_branches import executar_criar, executar_limpar
from agentes.orquestrador.agente_sync_push_main import executar as executar_sync_push_main
from core.config import (
    GIT_BRANCH_LIMPAR_APOS_PUSH,
    PUSH_DEPLOY_BRANCH,
    PUSH_DEPLOY_CRIAR_BRANCH,
    PUSH_DEPLOY_MENSAGEM_COMMIT,
    PUSH_DEPLOY_PATHS_EXCLUIR,
    PUSH_DEPLOY_REMOTE,
    PUSH_DEPLOY_RODAR_RUFF,
    PUSH_DEPLOY_RODAR_TESTES,
    ROOT,
)
from core.datadog_metrics import incrementar
from core.git_deploy import executar_push_deploy_git, obter_status
from core.notificador import alertar_gestor, gestor_telegram_configurado

logger = logging.getLogger("agente_push_deploy")


def _rodar_comando(cmd: list[str], *, descricao: str) -> dict[str, Any]:
    logger.info("Push deploy: %s — %s", descricao, " ".join(cmd))
    try:
        r = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        ok = r.returncode == 0
        if not ok:
            logger.error("Push deploy: %s falhou (exit %s)\n%s", descricao, r.returncode, r.stderr[-2000:])
        return {
            "ok": ok,
            "descricao": descricao,
            "exit_code": r.returncode,
            "stdout": (r.stdout or "")[-4000:],
            "stderr": (r.stderr or "")[-4000:],
        }
    except Exception as exc:
        logger.error("Push deploy: %s erro: %s", descricao, exc)
        return {"ok": False, "descricao": descricao, "erro": str(exc)}


def _preflight_qualidade(*, rodar_testes: bool, rodar_ruff: bool) -> dict[str, Any]:
    etapas: list[dict[str, Any]] = []
    if rodar_ruff:
        etapas.append(
            _rodar_comando([sys.executable, "-m", "ruff", "check", "."], descricao="ruff check")
        )
    if rodar_testes:
        etapas.append(
            _rodar_comando([sys.executable, "-m", "pytest", "-q"], descricao="pytest")
        )
    falhas = [e for e in etapas if not e.get("ok")]
    return {"ok": not falhas, "etapas": etapas, "falhas": len(falhas)}


def executar(
    *,
    mensagem_commit: str | None = None,
    branch: str | None = None,
    remote: str | None = None,
    dry_run_git: bool = False,
    pular_qualidade: bool = False,
    pular_push: bool = False,
    pular_agentes: bool = False,
    pular_limpeza_branches: bool = False,
    criar_branch: str | None = None,
    enviar_resumo_telegram: bool = True,
    rodar_testes: bool | None = None,
    rodar_ruff: bool | None = None,
) -> dict[str, Any]:
    """
    1. Preflight (ruff + pytest) opcional
    2. (Opcional) Criar branch a partir da main
    3. Git add/commit/push seguro
    4. Limpar branches mergeadas (local + remoto)
    5. Executa todos os agentes (listar_agentes_push_main)
    """
    msg = (mensagem_commit or PUSH_DEPLOY_MENSAGEM_COMMIT).strip()
    if not msg:
        msg = "chore: deploy automático robo-markplaces"

    rem = (remote or PUSH_DEPLOY_REMOTE).strip() or "origin"
    br = (branch or PUSH_DEPLOY_BRANCH).strip() or None
    excluir_paths = tuple(PUSH_DEPLOY_PATHS_EXCLUIR)

    resultado: dict[str, Any] = {
        "ok": True,
        "preflight": None,
        "branch_nova": None,
        "git": None,
        "limpeza_branches": None,
        "agentes": None,
    }

    if not pular_qualidade:
        pre = _preflight_qualidade(
            rodar_testes=PUSH_DEPLOY_RODAR_TESTES if rodar_testes is None else rodar_testes,
            rodar_ruff=PUSH_DEPLOY_RODAR_RUFF if rodar_ruff is None else rodar_ruff,
        )
        resultado["preflight"] = pre
        if not pre.get("ok"):
            resultado["ok"] = False
            incrementar("push_deploy.preflight.falha")
            if gestor_telegram_configurado():
                alertar_gestor(
                    "⚠️ Push deploy abortado: preflight falhou (ruff/pytest).\n"
                    "Corrija antes de enviar ao remoto."
                )
            return resultado

    nome_nova_branch = (criar_branch or PUSH_DEPLOY_CRIAR_BRANCH).strip() or None
    if nome_nova_branch:
        branch_res = executar_criar(nome_nova_branch, push_upstream=False)
        resultado["branch_nova"] = branch_res
        if not branch_res.get("ok"):
            resultado["ok"] = False
            incrementar("push_deploy.branch_nova.falha")
            return resultado
        br = branch_res.get("branch") or br

    if not pular_push:
        git_res = executar_push_deploy_git(
            mensagem_commit=msg,
            branch=br,
            remote=rem,
            dry_run=dry_run_git,
            paths_excluir=excluir_paths,
            cwd=ROOT,
        )
        resultado["git"] = git_res
        if not git_res.get("ok") and git_res.get("etapa"):
            resultado["ok"] = False
            incrementar("push_deploy.git.falha")
            return resultado
        if git_res.get("push_enviado"):
            incrementar("push_deploy.git.push_ok")
            logger.info("Push deploy: push enviado para %s/%s", rem, git_res.get("branch"))
        elif git_res.get("motivo"):
            logger.info("Push deploy git: %s", git_res["motivo"])
    else:
        status = obter_status(cwd=ROOT)
        resultado["git"] = {"ok": True, "pulado": True, "status": status}

    push_enviado = bool((resultado.get("git") or {}).get("push_enviado"))
    if (
        not pular_limpeza_branches
        and GIT_BRANCH_LIMPAR_APOS_PUSH
        and (push_enviado or pular_push)
    ):
        limpeza = executar_limpar(dry_run=dry_run_git)
        resultado["limpeza_branches"] = limpeza
        if not limpeza.get("ok"):
            logger.warning("Push deploy: limpeza de branches com falhas parciais")
            incrementar("push_deploy.limpeza_branches.falha")

    if not pular_agentes:
        logger.info("Push deploy: iniciando sync completo de agentes")
        agentes_res = executar_sync_push_main(enviar_resumo_telegram=enviar_resumo_telegram)
        resultado["agentes"] = agentes_res
        if agentes_res.get("falhas"):
            resultado["ok"] = False
        elif agentes_res.get("ok") is False:
            resultado["ok"] = False

    incrementar("push_deploy.rodadas", tags=[f"ok:{resultado['ok']}"])
    return resultado


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Push seguro + execução de todos os agentes")
    parser.add_argument("--mensagem", "-m", default=None, help="Mensagem do commit")
    parser.add_argument("--branch", "-b", default=None, help="Branch de destino (default: atual)")
    parser.add_argument("--remote", default=None, help="Remote git (default: origin)")
    parser.add_argument("--dry-run", action="store_true", help="Simula git sem commit/push")
    parser.add_argument("--sem-push", action="store_true", help="Não faz git; só roda agentes")
    parser.add_argument("--sem-agentes", action="store_true", help="Só faz push, não roda agentes")
    parser.add_argument("--sem-preflight", action="store_true", help="Pula ruff e pytest")
    parser.add_argument("--sem-telegram", action="store_true", help="Não envia resumo Telegram")
    parser.add_argument("--sem-limpeza-branches", action="store_true", help="Não remove branches mergeadas")
    parser.add_argument(
        "--criar-branch",
        metavar="NOME",
        default=None,
        help="Cria branch a partir da main antes do push (use 'auto')",
    )
    args = parser.parse_args(argv)

    logger.info("=== Push deploy (git + todos os agentes) ===")
    out = executar(
        mensagem_commit=args.mensagem,
        branch=args.branch,
        remote=args.remote,
        dry_run_git=args.dry_run,
        pular_qualidade=args.sem_preflight,
        pular_push=args.sem_push,
        pular_agentes=args.sem_agentes,
        pular_limpeza_branches=args.sem_limpeza_branches,
        criar_branch=args.criar_branch,
        enviar_resumo_telegram=not args.sem_telegram,
    )

    git = out.get("git") or {}
    agentes = out.get("agentes") or {}
    logger.info(
        "Push deploy concluído: ok=%s | push=%s | agentes_falhas=%s",
        out.get("ok"),
        git.get("push_enviado"),
        agentes.get("falhas"),
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
