"""
integracoes/veiculos/carros_batidos_fontes.py
Carrega catálogo de lojas de carros batidos/salvados.
"""
from __future__ import annotations

from typing import Any

from core.atomic_io import ler_json
from core.config import CARROS_BATIDOS_CATALOGO, ROOT


def carregar_fontes(catalogo_relativo: str | None = None) -> list[dict[str, Any]]:
    caminho = ROOT / (catalogo_relativo or CARROS_BATIDOS_CATALOGO)
    data = ler_json(caminho, default=[])
    if not isinstance(data, list):
        return []
    return [f for f in data if isinstance(f, dict) and f.get("ativo", True)]
