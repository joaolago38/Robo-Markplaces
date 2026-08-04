"""
Corrige dashboard Saúde: troca widgets de log quebrados por métricas reais.

Grupo \"Orquestrador - Execucao de Tarefas\" usava wildcards de log
(*Orquestrador*iniciando*) que retornam 0 hits. Substitui por:
  robo.orquestrador.agente.execucao / .erro / .ciclo / latencia by agente

Requer:
  DD_API_KEY + DD_APPLICATION_KEY no .env
  DD_SITE=us5.datadoghq.com

Uso:
  python scripts/corrigir_dashboards_datadog.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_env = ROOT / ".env"
if _env.is_file():
    for line in _env.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

DD_API_KEY = (os.getenv("DD_API_KEY") or "").strip()
DD_APPLICATION_KEY = (os.getenv("DD_APPLICATION_KEY") or "").strip()
DD_SITE = (os.getenv("DD_SITE") or "us5.datadoghq.com").strip() or "us5.datadoghq.com"

DASH_ID = "3iy-tka-awu"


def _headers() -> dict[str, str]:
    return {
        "DD-API-KEY": DD_API_KEY,
        "DD-APPLICATION-KEY": DD_APPLICATION_KEY,
        "Content-Type": "application/json",
    }


def _api(path: str) -> str:
    return f"https://api.{DD_SITE}{path}"


def _qv_metric(title: str, query: str, *, green_gt: float | None = 0, red_gt: float | None = None) -> dict:
    formats = []
    if red_gt is not None:
        formats.append({"comparator": ">", "palette": "white_on_red", "value": red_gt})
    if green_gt is not None:
        formats.append({"comparator": ">", "palette": "white_on_green", "value": green_gt})
    formats.append({"comparator": ">=", "palette": "white_on_green", "value": 0})
    return {
        "definition": {
            "title": title,
            "type": "query_value",
            "autoscale": True,
            "precision": 0,
            "requests": [
                {
                    "conditional_formats": formats,
                    "formulas": [{"formula": "query1"}],
                    "queries": [
                        {
                            "data_source": "metrics",
                            "name": "query1",
                            "query": query,
                        }
                    ],
                    "response_format": "scalar",
                    "aggregator": "sum",
                }
            ],
        }
    }


def _grupo_orquestrador_metricas() -> dict[str, Any]:
    """Substitui o grupo 100003 (logs quebrados) por métricas reais."""
    return {
        "id": 100003,
        "definition": {
            "title": "Orquestrador - Execucao de Tarefas",
            "type": "group",
            "background_color": "vivid_blue",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv_metric(
                        "Execucoes de Agentes",
                        "sum:robo.orquestrador.agente.execucao{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 0},
                    "id": 400001,
                },
                {
                    **_qv_metric(
                        "Agentes OK (media/ciclo)",
                        "avg:robo.orquestrador.ciclo.agentes_ok{*}",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 0},
                    "id": 400002,
                },
                {
                    **_qv_metric(
                        "Erros de Agente",
                        "sum:robo.orquestrador.agente.erro{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 0},
                    "id": 400003,
                },
                {
                    **_qv_metric(
                        "Ciclos Concluidos",
                        "sum:robo.orquestrador.ciclo{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 0},
                    "id": 400004,
                },
                {
                    "id": 400005,
                    "definition": {
                        "title": "Execucoes vs Erros (orquestrador)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "legend_columns": ["value", "sum"],
                        "requests": [
                            {
                                "display_type": "bars",
                                "response_format": "timeseries",
                                "style": {"palette": "datadog16"},
                                "formulas": [
                                    {"alias": "Execucoes", "formula": "query1"},
                                    {"alias": "Erros", "formula": "query2"},
                                    {"alias": "Ciclos", "formula": "query3"},
                                ],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "sum:robo.orquestrador.agente.execucao{*}.as_count()",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "sum:robo.orquestrador.agente.erro{*}.as_count()",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query3",
                                        "query": "sum:robo.orquestrador.ciclo{*}.as_count()",
                                    },
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 2},
                },
                {
                    "id": 400006,
                    "definition": {
                        "title": "Top Agentes por Execucao",
                        "type": "toplist",
                        "requests": [
                            {
                                "response_format": "scalar",
                                "formulas": [{"formula": "query1"}],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": (
                                            "sum:robo.orquestrador.agente.execucao{*} "
                                            "by {agente}.as_count()"
                                        ),
                                    }
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 2},
                },
            ],
        },
        "layout": {"x": 0, "y": 2, "width": 12, "height": 1},
    }


def get_dashboard(dash_id: str) -> dict[str, Any]:
    r = requests.get(_api(f"/api/v1/dashboard/{dash_id}"), headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def put_dashboard(body: dict[str, Any]) -> None:
    payload = {
        "title": body["title"],
        "description": (
            "Complemento ao dashboard principal. Orquestrador usa metricas "
            "robo.orquestrador.* (nao wildcards de log). Tokens, APIs, Claude, conectividade."
        ),
        "widgets": body["widgets"],
        "layout_type": body.get("layout_type") or "ordered",
        "template_variables": body.get("template_variables") or [],
        "notify_list": body.get("notify_list") or [],
        "reflow_type": body.get("reflow_type"),
        "tags": body.get("tags") or [],
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    r = requests.put(
        _api(f"/api/v1/dashboard/{DASH_ID}"),
        headers=_headers(),
        data=json.dumps(payload),
        timeout=60,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"PUT HTTP {r.status_code}: {(r.text or '')[:600]}")


def main() -> int:
    if not DD_API_KEY:
        print("FALHA: DD_API_KEY ausente")
        return 1
    if not DD_APPLICATION_KEY:
        print(
            "FALHA: DD_APPLICATION_KEY ausente no .env\n"
            "Adicione a Application Key (mesmo secret do GitHub) e rode de novo:\n"
            "  DD_APPLICATION_KEY=...\n"
            "Sem ela a API nao deixa atualizar o dashboard."
        )
        return 1

    raw = get_dashboard(DASH_ID)
    widgets = list(raw.get("widgets") or [])
    novo = []
    trocou = False
    for w in widgets:
        if w.get("id") == 100003 or (
            isinstance(w.get("definition"), dict)
            and w["definition"].get("title") == "Orquestrador - Execucao de Tarefas"
        ):
            novo.append(_grupo_orquestrador_metricas())
            trocou = True
        else:
            novo.append(w)
    if not trocou:
        print("Grupo Orquestrador nao encontrado — abortando")
        return 1
    raw["widgets"] = novo
    put_dashboard(raw)
    print(f"OK dashboard atualizado: https://us5.datadoghq.com/dashboard/{DASH_ID}")
    print(
        "Widgets agora usam: robo.orquestrador.agente.execucao / .erro / "
        "ciclo / ciclo.agentes_ok"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
