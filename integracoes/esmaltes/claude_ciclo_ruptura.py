"""
Ciclo Claude no ponto de ruptura:
  1) pulso de assertividade máxima para expor números âncora no Datadog
  2) depois volta a uso moderado (toggle, orçamento, profundidade padrão)

Segurança: SYSTEM_RUPTURA continua no modo moderado (não inventa número).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge

logger = logging.getLogger("claude_ciclo_ruptura")

CICLO_PATH = ROOT / "logs" / "claude_ciclo_ruptura.json"


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def ler_ciclo() -> dict[str, Any]:
    data = ler_json(CICLO_PATH, default={})
    return data if isinstance(data, dict) else {}


def fase_claude_ruptura() -> str:
    """maxima até os dados serem expostos no Datadog; depois moderada."""
    data = ler_ciclo()
    if data.get("exposto_datadog"):
        return "moderada"
    return "maxima"


def marcar_exposto_datadog() -> dict[str, Any]:
    """Após emitir gauges: próximo Claude da ruptura é moderado."""
    prev = ler_ciclo()
    out = {
        "fase": "moderada",
        "exposto_datadog": True,
        "exposto_em": prev.get("exposto_em") or _agora(),
        "ultimo_pulso_maxima_em": prev.get("ultimo_pulso_maxima_em"),
        "timestamp": _agora(),
    }
    if prev.get("fase") == "maxima" or not prev.get("exposto_datadog"):
        out["ultimo_pulso_maxima_em"] = prev.get("ultimo_pulso_maxima_em") or _agora()
    try:
        escrever_json_atomico(CICLO_PATH, out)
    except Exception:
        pass
    gauge("claude.ciclo.fase_maxima", 0.0)
    gauge("claude.ciclo.exposto_datadog", 1.0)
    return out


def registrar_pulso_maxima() -> None:
    data = ler_ciclo()
    data.update(
        {
            "fase": "maxima",
            "exposto_datadog": bool(data.get("exposto_datadog")),
            "ultimo_pulso_maxima_em": _agora(),
            "timestamp": _agora(),
        }
    )
    try:
        escrever_json_atomico(CICLO_PATH, data)
    except Exception:
        pass
    gauge("claude.ciclo.fase_maxima", 1.0)
    gauge("claude.ciclo.exposto_datadog", 1.0 if data.get("exposto_datadog") else 0.0)
