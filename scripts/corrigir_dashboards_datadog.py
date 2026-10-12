"""
Corrige dashboard Saúde (3iy-tka-awu): queries de log quebradas.

Causa dos "(No data)":
  1) Template vars $marketplace $componente → marketplace:* componente:*
     (exclui logs sem essas tags)
  2) Wildcards colados (*não*configurado*) que não batem em frases com espaço

Também troca o grupo Orquestrador por métricas robo.orquestrador.*.

Requer:
  DD_API_KEY + DD_APPLICATION_KEY no .env
  DD_SITE=us5.datadoghq.com

Uso:
  python scripts/corrigir_dashboards_datadog.py
"""
from __future__ import annotations

import json
import os
import re
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

# Frases reais nos logs → substituem wildcards colados
_GLUED: list[tuple[str, str]] = [
    ("*não*configurado*", '"não configurado"'),
    ("*nao*configurado*", '"nao configurado"'),
    ("*Não*configurado*", '"Não configurado"'),
    ("*Claude*bloqueado*", '"Claude bloqueado"'),
    ("*Claude*desligado*", '"Claude desligado"'),
    ("*Claude*estruturado*bloqueado*", '"Claude estruturado bloqueado"'),
    ("*Vigia*problemas*detectados*", '"Vigia: problemas detectados"'),
    ("*Vigia*problemas*", '"Vigia: problemas"'),
    ("*Orquestrador*iniciando*", '"Orquestrador: iniciando"'),
    ("*finalizado*ok=True*", '"finalizado ok=True"'),
    ("*finalizado*ok=False*", '"finalizado ok=False"'),
    ("*ciclo*concluído*", '"ciclo concluído"'),
    ("*Token*renovado*", '"Token renovado"'),
    ("*token*expirado*", '"token expirado"'),
    ("*token*inválido*", '"token inválido"'),
    ("*circuit*breaker*", '"circuit breaker"'),
    ("*DDG*bloqueado*", '"DDG bloqueado"'),
    ("*DDG*HTTP*403*", '"DDG" 403'),
    ("*DDG*vazio*", '"DDG" vazio'),
    ("*sem*resultados*", '"sem resultados"'),
    ("*403*bloqueada*", "403"),
    ("*Conectividade*FALHOU*", '"Conectividade" FALHOU'),
    ("*timed*out*", '"timed out"'),
    ("*Read*timed*out*", '"Read timed out"'),
    ("*Max*retries*exceeded*", '"Max retries exceeded"'),
    ("*Max*retries*", '"Max retries"'),
    ("*Falha*sincronizar*", "Falha sincronizar"),
    ("*CLAUDE_ATIVO=0*", "CLAUDE_ATIVO=0"),
]


def _headers() -> dict[str, str]:
    return {
        "DD-API-KEY": DD_API_KEY,
        "DD-APPLICATION-KEY": DD_APPLICATION_KEY,
        "Content-Type": "application/json",
    }


def _api(path: str) -> str:
    return f"https://api.{DD_SITE}{path}"


def corrigir_query_log(q: str) -> str:
    """Remove filtros de template var e descola wildcards."""
    out = q
    out = re.sub(r"\s*\$marketplace\b", "", out)
    out = re.sub(r"\s*\$componente\b", "", out)
    for old, new in _GLUED:
        out = out.replace(old, new)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _walk_fix_queries(obj: Any, stats: dict[str, int]) -> Any:
    if isinstance(obj, dict):
        novo = {}
        for k, v in obj.items():
            if k == "query" and isinstance(v, str) and "service:robo-markplaces" in v:
                fixed = corrigir_query_log(v)
                if fixed != v:
                    stats["queries"] += 1
                novo[k] = fixed
            elif k == "query_string" and isinstance(v, str) and "service:robo-markplaces" in v:
                fixed = corrigir_query_log(v)
                if fixed != v:
                    stats["queries"] += 1
                novo[k] = fixed
            elif k == "search" and isinstance(v, dict) and isinstance(v.get("query"), str):
                sq = v["query"]
                if "service:robo-markplaces" in sq:
                    fixed = corrigir_query_log(sq)
                    if fixed != sq:
                        stats["queries"] += 1
                    novo[k] = {**v, "query": fixed}
                else:
                    novo[k] = _walk_fix_queries(v, stats)
            else:
                novo[k] = _walk_fix_queries(v, stats)
        return novo
    if isinstance(obj, list):
        return [_walk_fix_queries(x, stats) for x in obj]
    return obj


def _qv_metric(
    title: str,
    query: str,
    *,
    green_gt: float | None = 0,
    red_gt: float | None = None,
    yellow_gt: float | None = None,
    aggregator: str = "sum",
) -> dict:
    formats = []
    if red_gt is not None:
        formats.append({"comparator": ">", "palette": "white_on_red", "value": red_gt})
    if yellow_gt is not None:
        formats.append({"comparator": ">", "palette": "white_on_yellow", "value": yellow_gt})
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
                    "aggregator": aggregator,
                }
            ],
        }
    }


def _qv_logs(title: str, query: str, *, yellow_gt: float = 0, red_gt: float | None = None) -> dict:
    formats = []
    if red_gt is not None:
        formats.append({"comparator": ">", "palette": "white_on_red", "value": red_gt})
    formats.append({"comparator": ">", "palette": "white_on_yellow", "value": yellow_gt})
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
                            "compute": {"aggregation": "count"},
                            "data_source": "logs",
                            "indexes": ["*"],
                            "name": "query1",
                            "search": {"query": query},
                        }
                    ],
                    "response_format": "scalar",
                }
            ],
        }
    }


def _grupo_orquestrador_metricas() -> dict[str, Any]:
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
                        aggregator="avg",
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


def _grupo_config_alertas() -> dict[str, Any]:
    """Configuracoes Ausentes: frases reais de log + metricas do vigia."""
    return {
        "id": 100005,
        "definition": {
            "title": "Configuracoes Ausentes e Alertas",
            "type": "group",
            "background_color": "vivid_purple",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    "id": 600001,
                    "definition": {
                        "type": "note",
                        "background_color": "purple",
                        "font_size": "12",
                        "has_padding": True,
                        "show_tick": False,
                        "text_align": "left",
                        "vertical_align": "top",
                        "content": (
                            "## Configuracoes Ausentes\n\n"
                            "Marketplaces e integracoes que **nao estao configurados** "
                            "ou estao com problemas:\n"
                            "- Shopee, Amazon, Magalu\n"
                            "- Meta Ads, Lojahub\n"
                            "- Claude (IA desligado)\n\n"
                            "Queries usam frases reais de log (sem marketplace:*/componente:*)."
                        ),
                    },
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 0},
                },
                {
                    **_qv_logs(
                        'Alertas "Nao Configurado"',
                        'service:robo-markplaces "não configurado"',
                        yellow_gt=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 0},
                    "id": 600002,
                },
                {
                    **_qv_logs(
                        "Claude Bloqueado",
                        (
                            "service:robo-markplaces "
                            '("Claude bloqueado" OR "Claude estruturado bloqueado" '
                            'OR "Claude desligado")'
                        ),
                        yellow_gt=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 0},
                    "id": 600003,
                },
                {
                    **_qv_metric(
                        "Vigia Datadog - Inatividades",
                        "avg:robo.vigia_datadog.inatividades{*}",
                        green_gt=None,
                        yellow_gt=0,
                        red_gt=3,
                        aggregator="avg",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 0},
                    "id": 600004,
                },
                {
                    "id": 600005,
                    "definition": {
                        "title": "Logs de Configuracoes Ausentes e Alertas Criticos",
                        "type": "list_stream",
                        "requests": [
                            {
                                "columns": [
                                    {"field": "status_line", "width": "compact"},
                                    {"field": "timestamp", "width": "auto"},
                                    {"field": "content", "width": "full"},
                                ],
                                "query": {
                                    "data_source": "logs_stream",
                                    "query_string": (
                                        "service:robo-markplaces "
                                        '("não configurado" OR "Claude bloqueado" '
                                        'OR "Claude desligado" OR "Vigia: problemas" '
                                        'OR "Conectividade" FALHOU OR invalid_grant)'
                                    ),
                                    "sort": {"column": "timestamp", "order": "desc"},
                                },
                                "response_format": "event_list",
                            }
                        ],
                    },
                    "layout": {"height": 4, "width": 12, "x": 0, "y": 2},
                },
            ],
        },
        "layout": {"x": 0, "y": 4, "width": 12, "height": 1},
    }


def get_dashboard(dash_id: str) -> dict[str, Any]:
    r = requests.get(_api(f"/api/v1/dashboard/{dash_id}"), headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def put_dashboard(body: dict[str, Any]) -> None:
    payload = {
        "title": body["title"],
        "description": (
            "Complemento ao dashboard principal. Orquestrador e Vigia usam metricas; "
            "demais grupos usam frases de log (sem marketplace:*/componente:*)."
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
            "Adicione a Application Key (mesmo secret do GitHub) e rode de novo.\n"
            "Sem ela a API nao deixa atualizar o dashboard.\n\n"
            "Enquanto isso: os dados JA EXISTEM.\n"
            '  - "não configurado": ~3500 logs / 30d\n'
            '  - "Claude bloqueado/desligado": centenas\n'
            "  - vigia inatividades: metrica ~3.5"
        )
        return 1

    raw = get_dashboard(DASH_ID)
    widgets = list(raw.get("widgets") or [])
    novo = []
    trocou_orc = False
    trocou_cfg = False
    for w in widgets:
        title = (w.get("definition") or {}).get("title") if isinstance(w.get("definition"), dict) else None
        if w.get("id") == 100003 or title == "Orquestrador - Execucao de Tarefas":
            novo.append(_grupo_orquestrador_metricas())
            trocou_orc = True
        elif w.get("id") == 100005 or title == "Configuracoes Ausentes e Alertas":
            novo.append(_grupo_config_alertas())
            trocou_cfg = True
        else:
            novo.append(w)

    stats = {"queries": 0}
    novo = _walk_fix_queries(novo, stats)
    raw["widgets"] = novo
    put_dashboard(raw)

    print(f"OK dashboard atualizado: https://us5.datadoghq.com/dashboard/{DASH_ID}")
    print(f"  Orquestrador -> metricas: {trocou_orc}")
    print(f"  Config/Alertas -> logs+vigia: {trocou_cfg}")
    print(f"  Queries de log corrigidas nos demais grupos: {stats['queries']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
