"""
core/claude_billing.py
Consulta o gasto real do mês na Anthropic (Usage & Cost Admin API).

O saldo pré-pago restante NÃO tem endpoint público. O custo do mês (centavos → US$)
sim: GET /v1/organizations/cost_report. Com isso o orçamento local/Datadog deixa
de publicar o teto CLAUDE_ORCAMENTO_USD (8.99) como se fosse crédito.

Requer ANTHROPIC_ADMIN_API_KEY (sk-ant-admin…). Contas individuais sem org
não têm Admin API — a sincronização cai no último snapshot do painel.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from core.http_client import request

logger = logging.getLogger("claude_billing")

COST_REPORT_URL = "https://api.anthropic.com/v1/organizations/cost_report"
ANTHROPIC_VERSION = "2023-06-01"
USER_AGENT = "Robo-Markplaces/1.0 (claude-billing-datadog)"


def chave_admin() -> str:
    from core.config import ANTHROPIC_ADMIN_API_KEY, ANTHROPIC_API_KEY

    admin = (ANTHROPIC_ADMIN_API_KEY or "").strip()
    if admin:
        return admin
    comum = (ANTHROPIC_API_KEY or "").strip()
    if comum.startswith("sk-ant-admin"):
        return comum
    return ""


def centavos_para_usd(amount: Any) -> float:
    """Cost API: amount em unidades mínimas (centavos) como string decimal."""
    try:
        return round(float(amount or 0) / 100.0, 6)
    except (TypeError, ValueError):
        return 0.0


def somar_custo_relatorio(payload: dict[str, Any] | None) -> float:
    total = 0.0
    if not isinstance(payload, dict):
        return 0.0
    for bucket in payload.get("data") or []:
        if not isinstance(bucket, dict):
            continue
        for row in bucket.get("results") or []:
            if isinstance(row, dict):
                total += centavos_para_usd(row.get("amount"))
    return round(total, 6)


def _inicio_fim_mes_utc(agora: datetime | None = None) -> tuple[str, str]:
    agora = agora or datetime.now(timezone.utc)
    inicio = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return inicio.strftime("%Y-%m-%dT00:00:00Z"), agora.strftime("%Y-%m-%dT00:00:00Z")


def consultar_custo_mes_console(*, agora: datetime | None = None) -> dict[str, Any]:
    """
    Soma o custo real do mês calendário (UTC) na Anthropic.
    Retorna {ok, gasto_mes_usd, fonte, motivo?} — nunca lança.
    """
    chave = chave_admin()
    if not chave:
        return {
            "ok": False,
            "gasto_mes_usd": None,
            "fonte": None,
            "motivo": "sem_admin_api_key",
        }
    starting_at, ending_at = _inicio_fim_mes_utc(agora)
    headers = {
        "x-api-key": chave,
        "anthropic-version": ANTHROPIC_VERSION,
        "user-agent": USER_AGENT,
    }
    total = 0.0
    page: str | None = None
    try:
        for _ in range(8):
            params: dict[str, Any] = {
                "starting_at": starting_at,
                "ending_at": ending_at,
                "bucket_width": "1d",
                "limit": 31,
            }
            if page:
                params["page"] = page
            url = f"{COST_REPORT_URL}?{urlencode(params)}"
            resp = request("GET", url, headers=headers, timeout=20)
            if resp.status_code >= 400:
                logger.warning(
                    "Cost API Anthropic HTTP %s — Datadog segue no último snapshot",
                    resp.status_code,
                )
                return {
                    "ok": False,
                    "gasto_mes_usd": None,
                    "fonte": None,
                    "motivo": f"http_{resp.status_code}",
                }
            payload = resp.json() if resp.content else {}
            total += somar_custo_relatorio(payload if isinstance(payload, dict) else {})
            if not isinstance(payload, dict) or not payload.get("has_more"):
                break
            page = payload.get("next_page")
            if not page:
                break
        return {
            "ok": True,
            "gasto_mes_usd": round(total, 6),
            "fonte": "console_api",
            "starting_at": starting_at,
            "ending_at": ending_at,
        }
    except Exception as exc:
        logger.warning("Cost API Anthropic falhou: %s", exc)
        return {
            "ok": False,
            "gasto_mes_usd": None,
            "fonte": None,
            "motivo": f"excecao:{type(exc).__name__}",
        }
