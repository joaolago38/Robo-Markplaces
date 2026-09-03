"""
integracoes/ml/coleta_avaliacoes.py
Texto de avaliações e perguntas de um item.

GET /reviews/item/{id} — documentação oficial (Products reviews) exige
Authorization: Bearer. Não é endpoint anônimo. Em rivais a app costuma
receber 403 PolicyAgent: lista vazia + log, não é bug do robô.

GET /questions/search?item_id= — Q&A do anúncio (api_version=4). Também
pede token na API atual. Formato: {questions:[{text, date_created, status}]}.
"""
from __future__ import annotations

import logging
from typing import Any

from core.datadog_metrics import incrementar
from core.http_client import request
from integracoes.ml import ml_client

logger = logging.getLogger("coleta_avaliacoes")

BASE = "https://api.mercadolibre.com"


def _headers() -> dict[str, str]:
    return ml_client._h() if ml_client._enabled() else {}


def _i(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def buscar_avaliacoes_item(item_id: str, limite: int = 50) -> list[dict[str, Any]]:
    """
    GET /reviews/item/{item_id} (token obrigatório).
    Campos: texto, nota_estrelas, data, titulo_curto.
    Falha/403 → [] (nunca lança).
    """
    iid = str(item_id or "").strip().upper()
    if not iid:
        return []
    try:
        r = request(
            "GET",
            f"{BASE}/reviews/item/{iid}",
            headers=_headers(),
            params={"limit": max(1, min(int(limite), 50))},
            timeout=20,
        )
        if r.status_code == 403:
            incrementar("ml.reviews.http_403")
            logger.warning(
                "reviews item=%s HTTP 403 — endpoint autenticado; texto de rival "
                "costuma ser PolicyAgent (limitação da API, não bug)",
                iid,
            )
            return []
        if r.status_code != 200:
            logger.warning("reviews item=%s HTTP %s", iid, r.status_code)
            return []
        body = r.json() or {}
        rows = body.get("reviews") or []
        saida: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            saida.append(
                {
                    "item_id": iid,
                    "texto": str(row.get("content") or row.get("text") or "").strip(),
                    "nota_estrelas": _i(row.get("rate") or row.get("rating")),
                    "data": str(row.get("date_created") or row.get("date") or ""),
                    "titulo_curto": str(row.get("title") or "").strip(),
                }
            )
        if saida:
            incrementar("ml.reviews.coletadas", float(len(saida)))
        return saida
    except Exception as exc:
        logger.warning("buscar_avaliacoes_item %s: %s", iid, exc)
        return []


def buscar_perguntas_item(item_id: str, limite: int = 50) -> list[dict[str, Any]]:
    """
    GET /questions/search?item_id=&api_version=4.
    Campos: texto, status, data. Falha → [].
    """
    iid = str(item_id or "").strip().upper()
    if not iid:
        return []
    try:
        r = request(
            "GET",
            f"{BASE}/questions/search",
            headers=_headers(),
            params={
                "item_id": iid,
                "api_version": 4,
                "limit": max(1, min(int(limite), 50)),
            },
            timeout=20,
        )
        if r.status_code != 200:
            logger.warning("perguntas item=%s HTTP %s", iid, r.status_code)
            return []
        body = r.json() or {}
        rows = body.get("questions") or []
        saida: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            saida.append(
                {
                    "item_id": iid,
                    "texto": str(row.get("text") or "").strip(),
                    "status": str(row.get("status") or ""),
                    "data": str(row.get("date_created") or ""),
                }
            )
        return saida
    except Exception as exc:
        logger.warning("buscar_perguntas_item %s: %s", iid, exc)
        return []
