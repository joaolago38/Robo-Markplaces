"""
core/produto_lookup.py
Resolve produto para chat/repricing: MLB → SKU do catálogo → Bling.
Nunca inventa estoque positivo sem fonte.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from core.catalogo_produtos import carregar_produtos_catalogo

logger = logging.getLogger("produto_lookup")

_PLACEHOLDER_MLB = frozenset({"", "MLB_PREENCHER", "MLB-PREENCHER"})
_MLB_RE = re.compile(r"^MLB\d+$", re.I)


def _norm_item_id(item_id: str) -> str:
    return (item_id or "").strip().upper().replace("-", "")


def item_id_ml_valido(item_id: str) -> bool:
    n = _norm_item_id(item_id)
    if n in _PLACEHOLDER_MLB or "PREENCHER" in n:
        return False
    return bool(_MLB_RE.match(n) or (n.startswith("MLB") and len(n) > 6 and n[3:].isdigit()))


def sku_por_item_id_ml(item_id: str) -> str | None:
    alvo = _norm_item_id(item_id)
    if not alvo or not item_id_ml_valido(alvo):
        return None
    for p in carregar_produtos_catalogo():
        ml = ((p.get("canais") or {}).get("mercadolivre") or {})
        if _norm_item_id(str(ml.get("item_id") or "")) == alvo:
            sku = str(p.get("sku") or "").strip()
            return sku or None
    return None


def produto_catalogo_por_item_id_ml(item_id: str) -> dict[str, Any] | None:
    alvo = _norm_item_id(item_id)
    if not alvo:
        return None
    for p in carregar_produtos_catalogo():
        ml = ((p.get("canais") or {}).get("mercadolivre") or {})
        if _norm_item_id(str(ml.get("item_id") or "")) == alvo:
            return p
    return None


def listar_ativos_com_mlb_placeholder() -> list[dict[str, str]]:
    """SKU ativos no catálogo ainda com MLB_PREENCHER (impede divulgação real)."""
    out: list[dict[str, str]] = []
    for p in carregar_produtos_catalogo():
        if not p.get("ativo", True):
            continue
        ml = ((p.get("canais") or {}).get("mercadolivre") or {})
        if not ml.get("ativo", False):
            continue
        item = str(ml.get("item_id") or "")
        if not item_id_ml_valido(item):
            out.append(
                {
                    "sku": str(p.get("sku") or ""),
                    "nome": str(p.get("nome") or "")[:80],
                    "item_id": item or "(vazio)",
                }
            )
    return out


def buscar_produto_por_ref(
    ref: str,
    *,
    canal: str = "mercadolivre",
) -> dict[str, Any] | None:
    """
    Busca produto no Bling.
    Se `ref` for item_id MLB, resolve SKU pelo catálogo primeiro.
    """
    ref = (ref or "").strip()
    if not ref:
        return None

    from integracoes.bling.bling_client import buscar_produto

    sku = ref
    cat: dict[str, Any] | None = None
    if canal.lower() in ("mercadolivre", "ml") and ref.upper().startswith("MLB"):
        cat = produto_catalogo_por_item_id_ml(ref)
        mapped = sku_por_item_id_ml(ref)
        if mapped:
            sku = mapped
        elif not item_id_ml_valido(ref):
            logger.info("item_id placeholder/inválido: %s", ref)
            return None
        else:
            logger.info("MLB %s sem SKU no catálogo — Bling por codigo provavelmente falha", ref)

    produto = buscar_produto(sku)
    if produto:
        return produto

    # Catálogo local sem inventar estoque positivo
    if cat:
        ml = (cat.get("canais") or {}).get("mercadolivre") or {}
        try:
            estoque = int(ml.get("estoque") if ml.get("estoque") is not None else cat.get("estoque") or 0)
        except (TypeError, ValueError):
            estoque = 0
        try:
            preco = float(ml.get("preco") or cat.get("preco") or 0)
        except (TypeError, ValueError):
            preco = 0.0
        return {
            "nome": cat.get("nome") or ml.get("titulo_anuncio") or "Produto",
            "sku": cat.get("sku") or sku,
            "codigo": cat.get("sku") or sku,
            "preco": preco,
            "estoque": max(0, estoque),
            "descricao": str(cat.get("descricao") or "")[:500],
            "_fonte": "catalogo_local",
        }
    return None
