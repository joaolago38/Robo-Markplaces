"""
integracoes/datadog/consulta_erros.py
Consulta erros no Datadog Log Management (opcional, requer DD_APPLICATION_KEY).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

logger = logging.getLogger("consulta_erros_datadog")


def buscar_erros_datadog(
    *,
    horas: float = 2.0,
    limite: int = 50,
    query: str | None = None,
) -> dict[str, Any]:
    """
    Busca logs de erro no Datadog. Retorna {ok, erros, motivo}.
  Sem DD_APPLICATION_KEY retorna ok=False e lista vazia (usa buffer local).
    """
    from core.config import DD_API_KEY, DD_APPLICATION_KEY, DD_ENV, DD_LOGS_ENABLED, DD_SITE

    if not DD_LOGS_ENABLED or not DD_API_KEY:
        return {"ok": False, "erros": [], "motivo": "datadog_desabilitado"}
    if not DD_APPLICATION_KEY:
        return {"ok": False, "erros": [], "motivo": "dd_application_key_ausente"}

    filtro = query or f"service:robo-markplaces env:{DD_ENV} status:error"
    agora = datetime.now(timezone.utc)
    inicio = agora - timedelta(hours=max(0.1, horas))

    body = {
        "filter": {
            "query": filtro,
            "from": inicio.isoformat(),
            "to": agora.isoformat(),
        },
        "page": {"limit": max(1, min(1000, limite))},
        "sort": "timestamp",
    }

    try:
        url = f"https://api.{DD_SITE}/api/v2/logs/events/search"
        r = requests.post(
            url,
            headers={
                "DD-API-KEY": DD_API_KEY,
                "DD-APPLICATION-KEY": DD_APPLICATION_KEY,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=15,
        )
        if r.status_code >= 400:
            return {
                "ok": False,
                "erros": [],
                "motivo": f"http_{r.status_code}",
                "detalhe": (r.text or "")[:200],
            }

        payload = r.json() or {}
        dados = payload.get("data") or []
        erros: list[dict[str, Any]] = []
        for item in dados:
            attrs = (item.get("attributes") or {}) if isinstance(item, dict) else {}
            erros.append(
                {
                    "id": item.get("id"),
                    "timestamp": attrs.get("timestamp"),
                    "mensagem": str(attrs.get("message") or "")[:500],
                    "status": attrs.get("status"),
                    "service": attrs.get("service"),
                    "tags": attrs.get("tags") or [],
                }
            )
        return {"ok": True, "erros": erros, "total": len(erros)}
    except Exception as exc:
        logger.warning("Consulta erros Datadog falhou: %s", exc)
        return {"ok": False, "erros": [], "motivo": "excecao", "detalhe": str(exc)[:200]}
