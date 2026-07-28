#!/usr/bin/env python3
"""
scripts/migrar_estado_para_dynamodb.py

Migração one-off e idempotente: lê JSONs locais e grava na tabela DynamoDB
com a mesma chave lógica usada por DynamoDBStateBackend.

Uso:
  export STORAGE_BACKEND=dynamodb
  export DYNAMODB_TABLE_NAME=robo-markplaces-state
  export AWS_REGION=us-east-1
  python scripts/migrar_estado_para_dynamodb.py

Rodar de novo sobrescreve os itens (PutItem) — não duplica nem corrompe.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import DYNAMODB_TABLE_NAME  # noqa: E402
from core.config import ROOT as PROJECT_ROOT
from core.state_backend import DynamoDBStateBackend, caminho_para_chave  # noqa: E402


def _coletar_arquivos() -> list[Path]:
    caminhos: list[Path] = []
    for rel in (
        "catalogo/produtos.json",
        "catalogo/concorrentes_monitorados.json",
    ):
        p = PROJECT_ROOT / rel
        if p.is_file():
            caminhos.append(p)
    dados_dir = PROJECT_ROOT / "dados"
    if dados_dir.is_dir():
        caminhos.extend(sorted(dados_dir.glob("*.json")))
    logs_dir = PROJECT_ROOT / "logs"
    if logs_dir.is_dir():
        for nome in ("marketplace_keepalive.json",):
            p = logs_dir / nome
            if p.is_file():
                caminhos.append(p)
    return caminhos


def migrar(dry_run: bool = False) -> int:
    arquivos = _coletar_arquivos()
    if not arquivos:
        print("Nenhum arquivo JSON encontrado para migrar.")
        return 0

    backend = DynamoDBStateBackend()
    print(f"Tabela DynamoDB: {DYNAMODB_TABLE_NAME}")
    print(f"Arquivos a migrar: {len(arquivos)}")

    ok = 0
    for caminho in arquivos:
        chave = caminho_para_chave(caminho)
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  [SKIP] {caminho}: leitura inválida ({exc})")
            continue
        if dry_run:
            print(f"  [DRY-RUN] {chave} <- {caminho}")
            ok += 1
            continue
        backend.escrever_json_atomico(caminho, dados)
        print(f"  [OK] {chave}")
        ok += 1

    print(f"Migração concluída: {ok}/{len(arquivos)} itens.")
    return 0 if ok == len(arquivos) else 1


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    return migrar(dry_run=dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
