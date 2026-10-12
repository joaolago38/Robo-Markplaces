"""
integracoes/mcp/ferramentas.py
Ferramentas do MCP local do robô — lêem o mesmo estado que o vigia/orquestrador.
Não substitui o intake HTTP do Datadog (logs/métricas no Actions).
"""
from __future__ import annotations

from typing import Any

from core.atomic_io import ler_json
from core.config import (
    DATADOG_VIGIA_CATALOGO_FONTES,
    DATADOG_VIGIA_LIMITE_HORAS_ERRO,
    DATADOG_VIGIA_LIMITE_HORAS_INATIVIDADE,
    ROOT,
)
from integracoes.datadog.consulta_erros import buscar_erros_datadog
from integracoes.datadog.vigia_saude import analisar_saude, carregar_fontes

CICLO_PATH = ROOT / "logs" / "orquestrador_ultimo_ciclo.json"


def vigia_saude() -> dict[str, Any]:
    """Roda o mesmo diagnóstico do agente vigia, sem Telegram."""
    fontes = carregar_fontes(DATADOG_VIGIA_CATALOGO_FONTES)
    analise = analisar_saude(
        fontes,
        limite_horas_inatividade=DATADOG_VIGIA_LIMITE_HORAS_INATIVIDADE,
        limite_horas_erro=DATADOG_VIGIA_LIMITE_HORAS_ERRO,
    )
    return {
        "ok": bool(analise.get("ok")),
        "tem_critico": bool(analise.get("tem_critico")),
        "total_inatividades": int(analise.get("total_inatividades") or 0),
        "total_erros": int(analise.get("total_erros") or 0),
        "agentes_com_problema": analise.get("agentes_com_problema") or [],
        "inatividades": analise.get("inatividades") or [],
        "erros": analise.get("erros") or [],
    }


def ultimo_ciclo() -> dict[str, Any]:
    """Último heartbeat gravado pelo orquestrador."""
    data = ler_json(CICLO_PATH, default={})
    if not isinstance(data, dict) or not data:
        return {"ok": False, "motivo": "ciclo_ausente", "path": str(CICLO_PATH)}
    return {"ok": True, **data}


def datadog_erros(*, horas: float = 2.0, limite: int = 30) -> dict[str, Any]:
    """Erros no Datadog via API REST (DD_API_KEY + DD_APPLICATION_KEY)."""
    return buscar_erros_datadog(horas=max(0.1, float(horas)), limite=max(1, min(100, int(limite))))
