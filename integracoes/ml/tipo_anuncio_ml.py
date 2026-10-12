"""
Tipo de anúncio ML: Premium vs Clássico, Full logístico vs envio comum.

gold_pro / gold_premium = Premium (mais exposição, taxa maior).
gold_special = Clássico.
logistic_type fulfillment = Mercado Envios Full (não confundir com Líder).

Taxa por tipo é faixa típica para não misturar prateleiras — não é a tabela
oficial do dia. Confira no publicador na hora de criar o anúncio.
"""
from __future__ import annotations

from typing import Any

PRATELEIRA_PREMIUM = "premium"
PRATELEIRA_CLASSICO = "classico"
PRATELEIRA_DESCONHECIDA = ""

_PREMIUM_IDS = frozenset({"gold_pro", "gold_premium"})
_CLASSICO_IDS = frozenset({"gold_special"})

# Faixa usada só quando o listing_type é conhecido. JSON Impala já usa 18% (Premium).
TAXA_ESTIMADA_PCT = {
    "gold_special": 12.0,
    "gold_pro": 18.0,
    "gold_premium": 18.0,
    "free": 0.0,
}

_FULL_LOGISTICA = frozenset({"fulfillment", "fulfillment_drop_off", "xd_drop_off"})


def listing_type_id_de(obj: dict[str, Any] | None) -> str:
    if not isinstance(obj, dict):
        return ""
    return str(obj.get("listing_type_id") or "").strip().lower()


def logistic_type_de(obj: dict[str, Any] | None) -> str:
    if not isinstance(obj, dict):
        return ""
    direto = str(obj.get("logistic_type") or "").strip().lower()
    if direto:
        return direto
    shipping = obj.get("shipping")
    if isinstance(shipping, dict):
        return str(shipping.get("logistic_type") or "").strip().lower()
    return ""


def prateleira(listing_type_id: str | None) -> str:
    lid = str(listing_type_id or "").strip().lower()
    if lid in _PREMIUM_IDS:
        return PRATELEIRA_PREMIUM
    if lid in _CLASSICO_IDS:
        return PRATELEIRA_CLASSICO
    return PRATELEIRA_DESCONHECIDA


def rotulo_prateleira(listing_type_id: str | None) -> str:
    p = prateleira(listing_type_id)
    if p == PRATELEIRA_PREMIUM:
        return "Premium"
    if p == PRATELEIRA_CLASSICO:
        return "Clássico"
    return "n/d"


def mesma_prateleira(tipo_a: str | None, tipo_b: str | None) -> bool:
    """Unknown não filtra (fail-open). Só separa quando os dois tipos são conhecidos."""
    pa, pb = prateleira(tipo_a), prateleira(tipo_b)
    if not pa or not pb:
        return True
    return pa == pb


def taxa_estimada_pct(listing_type_id: str | None, default: float = 13.0) -> float:
    lid = str(listing_type_id or "").strip().lower()
    if lid in TAXA_ESTIMADA_PCT:
        return float(TAXA_ESTIMADA_PCT[lid])
    return float(default)


def anuncio_e_full(obj: dict[str, Any] | None) -> bool:
    return logistic_type_de(obj) in _FULL_LOGISTICA


def algum_anuncio_full(anuncios: list[dict[str, Any]] | None) -> bool:
    return any(anuncio_e_full(a) for a in (anuncios or []) if isinstance(a, dict))


def contar_prateleiras(anuncios: list[dict[str, Any]] | None) -> dict[str, int]:
    premium = classico = outro = 0
    for a in anuncios or []:
        if not isinstance(a, dict):
            continue
        p = prateleira(listing_type_id_de(a))
        if p == PRATELEIRA_PREMIUM:
            premium += 1
        elif p == PRATELEIRA_CLASSICO:
            classico += 1
        else:
            outro += 1
    return {"premium": premium, "classico": classico, "outro": outro, "total": premium + classico + outro}
