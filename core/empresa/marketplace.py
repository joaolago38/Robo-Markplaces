"""core/empresa/marketplace.py — nomes de marketplace (SRP)."""
from __future__ import annotations

MARKETPLACES_CONHECIDOS = frozenset(
    {"mercadolivre", "shopee", "magalu", "amazon", "loja_propria"}
)

_ALIASES = {
    "ml": "mercadolivre",
    "mercadolivre": "mercadolivre",
    "mercadolibre": "mercadolivre",
    "mlb": "mercadolivre",
    "shopee": "shopee",
    "magalu": "magalu",
    "magazinevoce": "magalu",
    "amazon": "amazon",
    "loja": "loja_propria",
    "lojapropria": "loja_propria",
}


def norm_marketplace(nome: str) -> str:
    n = str(nome or "").strip().lower().replace(" ", "").replace("-", "")
    return _ALIASES.get(n, n)
