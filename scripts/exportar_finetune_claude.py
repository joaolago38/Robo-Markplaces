#!/usr/bin/env python3
"""
Exporta o JSONL de fine-tuning do Claude 3 Haiku (Bedrock).

Cada linha aprovada traz proposito + entrada + resposta. O system sai do
playbook daquele proposito. O roteador descarta o que iria para o Sonnet.

Uso:
  python scripts/exportar_finetune_claude.py
  python scripts/exportar_finetune_claude.py --entrada catalogo/claude_finetune_aprovados.jsonl

Formato de cada linha de entrada:
  {"proposito":"sazonal","entrada":"...","resposta":"...","campos":{"nicho":"esmaltes"}}

Linha com "aprovado": false é candidato e fica de fora.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from core.claude_finetune import (
        APROVADOS_PATH,
        SAIDA_PATH,
        carregar_pares,
        exportar_jsonl,
    )

    parser = argparse.ArgumentParser(description="Monta o JSONL de fine-tuning Haiku")
    parser.add_argument("--entrada", type=Path, default=APROVADOS_PATH)
    parser.add_argument("--saida", type=Path, default=SAIDA_PATH)
    args = parser.parse_args()

    if not args.entrada.is_file():
        print(f"Arquivo de pares aprovados não encontrado: {args.entrada}")
        print(
            'Inclua uma linha JSON por exemplo: '
            '{"proposito":"sazonal","entrada":"...","resposta":"..."}'
        )
        return 1

    pares = carregar_pares(args.entrada)
    resumo = exportar_jsonl(pares, args.saida)
    print(
        f"Base {resumo['base']}: {resumo['gravadas']} linha(s) em {resumo['destino']}"
    )
    for recusa in resumo["recusadas"]:
        print(
            f"  recusada [{recusa['indice']}] {recusa.get('proposito')}: {recusa['motivo']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
