"""
agentes/orquestrador/runners.py
Wrappers para scripts sem módulo importável padrão.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _carregar_script(nome_arquivo: str):
    caminho = ROOT / "scripts" / nome_arquivo
    spec = importlib.util.spec_from_file_location(f"scripts_{nome_arquivo}", caminho)
    if spec is None or spec.loader is None:
        raise ImportError(f"Script não encontrado: {caminho}")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def executar_renovar_tokens() -> dict[str, Any]:
    modulo = _carregar_script("renovar_tokens.py")
    codigo = int(modulo.main())
    return {"ok": codigo == 0, "exit_code": codigo}
