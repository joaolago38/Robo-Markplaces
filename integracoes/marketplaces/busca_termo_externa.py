"""
integracoes/marketplaces/busca_termo_externa.py
Busca por termo em marketplaces via Brave/DDG (site:dominio).
Usado quando a API do marketplace não expõe busca pública por palavra-chave.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from core.config import BRAVE_SEARCH_API_KEY
from core.ddg_lite import buscar as ddg_buscar
from core.http_client import request

logger = logging.getLogger("busca_termo_externa")

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_RE_PRECO = re.compile(r"R\$\s*([\d]{1,3}(?:\.\d{3})*,\d{2}|\d+[,\.]\d{2})")

_META_MARKETPLACES: dict[str, dict[str, str]] = {
    "magalu": {"dominio": "magazineluiza.com.br", "label": "Magalu"},
    "shopee": {"dominio": "shopee.com.br", "label": "Shopee"},
    "amazon": {"dominio": "amazon.com.br", "label": "Amazon"},
}


def _parse_preco(texto: str) -> float:
    m = _RE_PRECO.search(texto or "")
    if not m:
        return 0.0
    bruto = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(bruto)
    except ValueError:
        return 0.0


def _id_de_url(url: str, marketplace: str) -> str:
    h = hashlib.sha256(f"{marketplace}:{url}".encode()).hexdigest()[:12]
    return f"{marketplace.upper()}-{h}"


def _normalizar_hit(
    hit: dict[str, str],
    *,
    marketplace: str,
    fonte: str,
) -> dict[str, Any]:
    url = str(hit.get("url") or "").strip()
    titulo = str(hit.get("titulo") or hit.get("title") or "").strip()
    snippet = str(hit.get("snippet") or hit.get("description") or "")
    preco = _parse_preco(f"{titulo} {snippet}")
    return {
        "item_id": _id_de_url(url, marketplace),
        "titulo": titulo[:200],
        "preco": preco,
        "frete_gratis": "frete grátis" in f"{titulo} {snippet}".lower(),
        "condicao": "",
        "quantidade_vendida": 0,
        "seller_id": "",
        "permalink": url,
        "marketplace": marketplace,
        "fonte_busca": fonte,
    }


def _buscar_brave_site(dominio: str, termo: str, limite: int) -> list[dict[str, str]]:
    if not BRAVE_SEARCH_API_KEY:
        return []
    query = f"site:{dominio} {termo}"
    try:
        r = request(
            "GET",
            _BRAVE_URL,
            params={"q": query, "count": max(1, min(20, limite))},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
            },
            timeout=20,
        )
        if r.status_code >= 400:
            return []
        body = r.json() or {}
        brutos = (body.get("web") or {}).get("results") or []
        out: list[dict[str, str]] = []
        for row in brutos:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "")
            if dominio not in url.lower():
                continue
            out.append(
                {
                    "url": url,
                    "titulo": str(row.get("title") or ""),
                    "snippet": str(row.get("description") or ""),
                }
            )
        return out
    except Exception as exc:
        logger.debug("Brave site:%s termo=%r: %s", dominio, termo[:50], exc)
        return []


def _buscar_ddg_site(dominio: str, termo: str, limite: int) -> list[dict[str, str]]:
    query = f"site:{dominio} {termo}"
    try:
        brutos = ddg_buscar(query, max_resultados=max(limite * 2, 10), contexto=f"mp_{dominio}")
    except Exception:
        return []
    out: list[dict[str, str]] = []
    for hit in brutos:
        url = str(hit.get("url") or hit.get("link") or "")
        if dominio not in url.lower():
            continue
        out.append(
            {
                "url": url,
                "titulo": str(hit.get("titulo") or hit.get("title") or ""),
                "snippet": str(hit.get("snippet") or ""),
            }
        )
    return out


def buscar_por_termo(marketplace: str, termo: str, *, limite: int = 20) -> list[dict[str, Any]]:
    """
    Busca anúncios/produtos em Magalu, Shopee ou Amazon via web (Brave → DDG).
    Retorna lista no formato normalizado do ML. Nunca lança exceção.
    """
    mp = (marketplace or "").strip().lower()
    meta = _META_MARKETPLACES.get(mp)
    termo = (termo or "").strip()
    if not meta or not termo:
        return []

    dominio = meta["dominio"]
    limite = max(1, min(30, limite))
    vistos: set[str] = set()
    encontrados: list[dict[str, Any]] = []

    for fonte, buscar in (("brave", _buscar_brave_site), ("ddg", _buscar_ddg_site)):
        hits = buscar(dominio, termo, limite)
        for hit in hits:
            url = hit.get("url") or ""
            if not url or url in vistos:
                continue
            vistos.add(url)
            norm = _normalizar_hit(hit, marketplace=mp, fonte=fonte)
            if norm.get("titulo"):
                encontrados.append(norm)
            if len(encontrados) >= limite:
                break
        if encontrados:
            logger.info("Busca %s termo=%r fonte=%s → %d", mp, termo[:50], fonte, len(encontrados))
            return encontrados

    return encontrados
