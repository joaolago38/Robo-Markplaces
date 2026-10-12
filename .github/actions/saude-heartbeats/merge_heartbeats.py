"""
Escolhe, arquivo a arquivo, o heartbeat mais novo.

Um job que restaurou o cache no início e só publica no fim republicava
timestamps velhos por cima de um produtor que terminou no meio. No save,
a cópia deste job é comparada com o cache mais recente.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

CAMPOS = (
    "timestamp",
    "ultima_varredura",
    "ultima_execucao",
    "coletado_em",
    "atualizado_em",
)


def caminhos(catalogo: Path) -> list[str]:
    saida: list[str] = []
    for linha in catalogo.read_text(encoding="utf-8").splitlines():
        s = linha.strip()
        if s and not s.startswith("#"):
            saida.append(s)
    return saida


def _parse(valor: object) -> datetime | None:
    if not isinstance(valor, str) or not valor.strip():
        return None
    texto = valor.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(texto)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt


def instante(path: Path) -> float:
    """Segundos desde a época. Sem data no JSON, usa o mtime do arquivo."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    if isinstance(data, dict):
        for campo in CAMPOS:
            dt = _parse(data.get(campo))
            if dt is not None:
                return dt.timestamp()
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def mais_novo(esquerda: Path, direita: Path) -> Path | None:
    tem_esq = esquerda.is_file()
    tem_dir = direita.is_file()
    if not tem_esq and not tem_dir:
        return None
    if not tem_esq:
        return direita
    if not tem_dir:
        return esquerda
    if instante(esquerda) >= instante(direita):
        return esquerda
    return direita


def guardar(raiz: Path, destino: Path, nomes: list[str]) -> None:
    for rel in nomes:
        origem = raiz / rel
        if not origem.is_file():
            continue
        alvo = destino / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, alvo)


def mesclar(job: Path, cache: Path, nomes: list[str]) -> list[str]:
    """Grava em `cache` o arquivo mais novo entre `job` e `cache`."""
    escolhidos: list[str] = []
    for rel in nomes:
        winner = mais_novo(job / rel, cache / rel)
        if winner is None:
            continue
        dest = cache / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if winner.resolve() != dest.resolve():
            shutil.copy2(winner, dest)
        escolhidos.append(rel)
    return escolhidos


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("uso: merge_heartbeats.py stage|merge <dir> [<raiz>]", file=sys.stderr)
        return 2
    raiz = Path(argv[3]) if len(argv) > 3 else Path(".")
    catalogo = raiz / "catalogo" / "saude_heartbeats_paths.txt"
    nomes = caminhos(catalogo)
    cmd, destino = argv[1], Path(argv[2])
    if cmd == "stage":
        guardar(raiz, destino, nomes)
        return 0
    if cmd == "merge":
        mesclar(destino, raiz, nomes)
        return 0
    print(f"comando desconhecido: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
