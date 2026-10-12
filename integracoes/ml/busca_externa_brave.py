"""
integracoes/ml/busca_externa_brave.py
Busca web via Brave Search API (JSON) — alternativa ao DDG quando bloqueado.

Requer BRAVE_SEARCH_API_KEY. Cota mensal controlada em core.brave_search.
https://brave.com/search/api/
"""
from __future__ import annotations

import logging

from core.brave_search import buscar_web
from core.config import BRAVE_SEARCH_API_KEY

logger = logging.getLogger("busca_externa_brave")


def _enabled() -> bool:
    return bool(BRAVE_SEARCH_API_KEY)


def buscar_mercadolivre(termo: str, *, limite: int = 15) -> list[dict[str, str]]:
    """
    Busca `site:mercadolivre.com.br {termo}` na Brave Search API.
    Retorna lista de {url, titulo, snippet}. Nunca lança exceção.
    """
    termo = (termo or "").strip()
    if not termo or not _enabled():
        return []

    query = f"site:mercadolivre.com.br {termo}"
    brutos = buscar_web(query, limite=max(1, min(20, limite)), contexto="ml_busca_termo")
    out: list[dict[str, str]] = []
    for row in brutos:
        url = str(row.get("url") or "").strip()
        if "mercadolivre.com.br" not in url.lower():
            continue
        out.append(
            {
                "url": url,
                "titulo": str(row.get("titulo") or ""),
                "snippet": str(row.get("snippet") or ""),
            }
        )
        if len(out) >= limite:
            break
    return out
