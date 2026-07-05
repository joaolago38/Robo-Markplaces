"""
agentes/orquestrador/agente_git_branches.py
Mantém o repositório limpo (remove branches mergeadas) e cria novas branches a partir da main.

Uso local:
  python -m agentes.orquestrador.agente_git_branches --limpar
  python -m agentes.orquestrador.agente_git_branches --criar cursor/minha-feature
  python -m agentes.orquestrador.agente_git_branches --criar auto --push

Após cada push (agente_push_deploy), a limpeza roda automaticamente se GIT_BRANCH_LIMPAR_APOS_PUSH=1.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.config import (
    GIT_BRANCH_BASE,
    GIT_BRANCH_LIMPAR_LOCAIS,
    GIT_BRANCH_LIMPAR_REMOTAS,
    GIT_BRANCH_NOVA_PREFIXO,
    GIT_BRANCH_PREFIXOS_LIMPEZA,
    GIT_BRANCH_PROTEGIDAS,
    GIT_BRANCH_REMOTE,
    ROOT,
)
from core.datadog_metrics import incrementar
from core.git_deploy import criar_branch_de_main, executar_limpeza_branches

logger = logging.getLogger("agente_git_branches")


def _gerar_nome_branch_auto() -> str:
    prefixo = GIT_BRANCH_NOVA_PREFIXO or "cursor/"
    if prefixo and not prefixo.endswith("/"):
        prefixo = prefixo + "/"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return f"{prefixo}{stamp}"


def executar_limpar(
    *,
    dry_run: bool = False,
    limpar_remotas: bool | None = None,
    limpar_locais: bool | None = None,
) -> dict[str, Any]:
    out = executar_limpeza_branches(
        base=GIT_BRANCH_BASE,
        remote=GIT_BRANCH_REMOTE,
        protegidas=GIT_BRANCH_PROTEGIDAS,
        prefixos=GIT_BRANCH_PREFIXOS_LIMPEZA,
        limpar_remotas=GIT_BRANCH_LIMPAR_REMOTAS if limpar_remotas is None else limpar_remotas,
        limpar_locais=GIT_BRANCH_LIMPAR_LOCAIS if limpar_locais is None else limpar_locais,
        dry_run=dry_run,
        cwd=ROOT,
    )
    if out.get("ok"):
        incrementar(
            "git_branches.limpeza.ok",
            tags=[
                f"remotas:{len(out.get('remotas_deletadas') or [])}",
                f"locais:{len(out.get('locais_deletadas') or [])}",
            ],
        )
    else:
        incrementar("git_branches.limpeza.falha")
    return out


def executar_criar(
    nome: str,
    *,
    push_upstream: bool = False,
) -> dict[str, Any]:
    nome_final = _gerar_nome_branch_auto() if (nome or "").strip().lower() == "auto" else (nome or "").strip()
    if not nome_final:
        return {"ok": False, "motivo": "informe o nome da branch ou use 'auto'"}

    out = criar_branch_de_main(
        nome_final,
        base=GIT_BRANCH_BASE,
        remote=GIT_BRANCH_REMOTE,
        push_upstream=push_upstream,
        cwd=ROOT,
    )
    if out.get("ok"):
        incrementar("git_branches.criar.ok", tags=[f"criada:{out.get('criada')}"])
        logger.info(
            "Branch %s (%s) a partir de %s",
            nome_final,
            "criada" if out.get("criada") else "checkout",
            GIT_BRANCH_BASE,
        )
    else:
        incrementar("git_branches.criar.falha")
    return out


def executar(
    *,
    limpar: bool = True,
    criar_branch: str | None = None,
    push_nova_branch: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    resultado: dict[str, Any] = {"ok": True, "criar": None, "limpar": None}

    if criar_branch:
        criar_res = executar_criar(criar_branch, push_upstream=push_nova_branch)
        resultado["criar"] = criar_res
        if not criar_res.get("ok"):
            resultado["ok"] = False
            return resultado

    if limpar:
        limpar_res = executar_limpar(dry_run=dry_run)
        resultado["limpar"] = limpar_res
        if not limpar_res.get("ok"):
            resultado["ok"] = False

    incrementar("git_branches.rodadas", tags=[f"ok:{resultado['ok']}"])
    return resultado


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Limpar branches mergeadas e/ou criar nova branch a partir da main"
    )
    parser.add_argument("--limpar", action="store_true", help="Remove branches já mergeadas na main")
    parser.add_argument("--criar", "-c", metavar="NOME", help="Cria branch a partir da main (use 'auto' para nome automático)")
    parser.add_argument("--push", action="store_true", help="Envia a nova branch ao remoto (-u origin)")
    parser.add_argument("--dry-run", action="store_true", help="Simula limpeza sem deletar")
    parser.add_argument("--sem-limpar", action="store_true", help="Não limpa branches")
    args = parser.parse_args(argv)

    fazer_limpar = args.limpar or (not args.criar and not args.sem_limpar)
    if args.criar and not args.limpar:
        fazer_limpar = False

    logger.info("=== Git branches (main=%s) ===", GIT_BRANCH_BASE)
    out = executar(
        limpar=fazer_limpar and not args.sem_limpar,
        criar_branch=args.criar,
        push_nova_branch=args.push,
        dry_run=args.dry_run,
    )

    limpar = out.get("limpar") or {}
    criar = out.get("criar") or {}
    logger.info(
        "Git branches concluído: ok=%s | remotas_removidas=%s | locais_removidas=%s | branch=%s",
        out.get("ok"),
        len(limpar.get("remotas_deletadas") or []),
        len(limpar.get("locais_deletadas") or []),
        criar.get("branch"),
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
