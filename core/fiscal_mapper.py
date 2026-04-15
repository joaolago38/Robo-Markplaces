"""
core/fiscal_mapper.py
Regras fiscais para resolver NCM e montar itens para NF-e.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
CATALOGO_PATH = ROOT / "catalogo" / "produtos.json"
_NCM_RE = re.compile(r"^\d{8}$")


def _somente_digitos(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def ncm_valido(ncm: str) -> bool:
    return bool(_NCM_RE.match(_somente_digitos(ncm)))


def _carregar_catalogo() -> list[dict]:
    if not CATALOGO_PATH.exists():
        return []
    try:
        with open(CATALOGO_PATH, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def buscar_ncm_por_sku(sku: str) -> str | None:
    sku_upper = (sku or "").strip().upper()
    for p in _carregar_catalogo():
        if str(p.get("sku", "")).strip().upper() == sku_upper:
            ncm = _somente_digitos(p.get("ncm", ""))
            return ncm if ncm_valido(ncm) else None
    return None


def resolver_ncm_item(item: dict, produto_bling: dict | None = None) -> str | None:
    # Prioridade: item > Bling > catálogo.
    ncm_item = _somente_digitos(item.get("ncm", ""))
    if ncm_valido(ncm_item):
        return ncm_item

    if produto_bling:
        ncm_bling = _somente_digitos(produto_bling.get("ncm", ""))
        if ncm_valido(ncm_bling):
            return ncm_bling

    return buscar_ncm_por_sku(item.get("sku", ""))
