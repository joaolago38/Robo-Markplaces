"""
integracoes/ml/busca_externa_brave.py
Busca web via Brave Search API (JSON) — alternativa ao DDG quando bloqueado.

Requer BRAVE_SEARCH_API_KEY (plano gratuito: ~2000 consultas/mês).
https://brave.com/search/api/
"""
from __future__ import annotations

import logging
from typing import Any

from core.config import BRAVE_SEARCH_API_KEY
from core.http_client import request

logger = logging.getLogger("busca_externa_brave")

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


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
        if r.status_code == 401:
            logger.warning("Brave Search API: chave inválida (401)")
            return []
        if r.status_code == 429:
            logger.warning("Brave Search API: rate limit (429) termo=%r", termo[:60])
            return []
        if r.status_code >= 400:
            logger.warning("Brave Search API HTTP %s termo=%r", r.status_code, termo[:60])
            return []

        body = r.json() or {}
        web = body.get("web") or {}
        brutos = web.get("results") or []
        out: list[dict[str, str]] = []
        for row in brutos:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            if "mercadolivre.com.br" not in url.lower():
                continue
            out.append(
                {
                    "url": url,
                    "titulo": str(row.get("title") or ""),
                    "snippet": str(row.get("description") or ""),
                }
            )
            if len(out) >= limite:
                break

        if out:
            logger.info("Brave Search OK termo=%r resultados=%d", termo[:60], len(out))
        return out
    except Exception as exc:
        logger.warning("Brave Search erro termo=%r: %s", termo[:60], exc)
        return []
