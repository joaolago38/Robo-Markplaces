"""
Completa observabilidade Datadog do Robo Marketplaces:

1) Dashboard Saude (3iy-tka-awu): grupo [Metricas] Chat / NF-e / Estoque / Telegram / Repricing
2) Monitores de alerta (orquestrador, vigia, Claude, Magalu auth, Telegram)

Requer DD_API_KEY + DD_APPLICATION_KEY no .env
  DD_SITE=us5.datadoghq.com

Uso:
  python scripts/completar_datadog_saude.py
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

DASH_SAUDE = "3iy-tka-awu"
DASH_OPS = "7be-b7r-nrk"
GROUP_PONTOS_CEGOS_ID = 700005
GROUP_TOKENS_ID = 100001
GROUP_CATALOGO_IMPALA_ID = 700006
GROUP_BATALHA_IMPALA_ID = 700007
TAG_MONITOR = "service:robo-markplaces"

# ── Queries de log do grupo "Tokens e Autenticacao" ───────────────────────
# O widget antigo usava (*401* OR *token* OR *Token*), que casava com a DICA
# "verifique ML_ACCESS_TOKEN/refresh" dentro do aviso de HTTP 403 da busca do
# ML. Resultado: ~87% do painel era 403 de busca, nao problema de credencial.
# Agora cada caixa tem um significado unico.

# Credencial realmente morta — exige acao manual (reautorizar/regerar secret).
Q_OAUTH_MORTO = (
    "service:robo-markplaces (status:error OR status:warn) "
    '-"buscar_concorrentes_por_termo" -"nao configurado" -"não configurado" '
    '(invalid_grant OR invalid_client OR "token inválido" OR "token expirado" '
    'OR "Erro ao renovar token" OR "Regenere token")'
)
# 401 do Bling que o robo renova sozinho na sequencia: informativo, nao erro.
Q_BLING_AUTO = 'service:robo-markplaces "Bling retornou 401"'
# Restricao do endpoint /sites/MLB/search — nao e token; tem fallback proprio.
Q_ML_BUSCA_403 = 'service:robo-markplaces "buscar_concorrentes_por_termo" "HTTP 403"'
# Rate limit de verdade (sem wildcard *429*, que pegava IDs contendo 429).
Q_RATE_LIMIT = (
    "service:robo-markplaces "
    '("HTTP 429" OR "429 Client Error" OR "status=429" OR "Too Many Requests")'
)


def _headers() -> dict[str, str]:
    return {
        "DD-API-KEY": DD_API_KEY,
        "DD-APPLICATION-KEY": DD_APPLICATION_KEY,
        "Content-Type": "application/json",
    }


def _api(path: str) -> str:
    return f"https://api.{DD_SITE}{path}"


def _get(path: str) -> Any:
    r = requests.get(_api(path), headers=_headers(), timeout=45)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict[str, Any]) -> Any:
    r = requests.post(_api(path), headers=_headers(), data=json.dumps(body), timeout=45)
    if r.status_code >= 300:
        raise RuntimeError(f"POST {path} HTTP {r.status_code}: {(r.text or '')[:800]}")
    return r.json()


def _put(path: str, body: dict[str, Any]) -> Any:
    r = requests.put(_api(path), headers=_headers(), data=json.dumps(body), timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"PUT {path} HTTP {r.status_code}: {(r.text or '')[:800]}")
    return r.json() if r.text else {}


def _qv(
    title: str,
    query: str,
    *,
    aggregator: str = "sum",
    red_gt: float | None = None,
    yellow_gt: float | None = None,
    green_gt: float | None = 0,
    precision: int = 0,
) -> dict[str, Any]:
    formats: list[dict[str, Any]] = []
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
            "precision": precision,
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


def _lv(
    title: str,
    query: str,
    *,
    palette: str = "white_on_red",
    value: float = 0,
) -> dict[str, Any]:
    """query_value sobre logs (contagem)."""
    return {
        "definition": {
            "title": title,
            "type": "query_value",
            "autoscale": True,
            "precision": 0,
            "requests": [
                {
                    "conditional_formats": [
                        {"comparator": ">", "palette": palette, "value": value}
                    ],
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


def _grupo_tokens() -> dict[str, Any]:
    """Grupo Tokens/Auth com cada caixa medindo uma coisa so.

    Separa credencial morta (acao manual) de ruido esperado: 401 do Bling que
    auto-renova e 403 do /sites/MLB/search, que nao tem relacao com token.
    """
    nota = (
        "## Tokens e Auth\n\n"
        "- **OAuth morto** — credencial nao se cura sozinha; reautorizar/regerar "
        "secret. Ex.: Magalu `invalid_grant`.\n"
        "- **Bling 401 auto-renovado** — esperado; robo renova na sequencia.\n"
        "- **ML busca 403** — restricao do `/sites/MLB/search`, **nao** e token; "
        "cai em catalogo/Brave/DDG.\n"
        "- **429** — rate limit (cotacao USD, PNCP)."
    )
    return {
        "id": GROUP_TOKENS_ID,
        "definition": {
            "title": "Tokens e Autenticacao",
            "type": "group",
            "background_color": "vivid_red",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    "definition": {
                        "type": "note",
                        "content": nota,
                        "background_color": "red",
                        "font_size": "12",
                        "has_padding": True,
                        "show_tick": False,
                        "text_align": "left",
                        "vertical_align": "top",
                    },
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 0},
                    "id": 200001,
                },
                {
                    **_lv("OAuth morto (acao manual)", Q_OAUTH_MORTO),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 0},
                    "id": 200002,
                },
                {
                    **_lv(
                        "ML busca 403 (limite da API, nao token)",
                        Q_ML_BUSCA_403,
                        palette="white_on_yellow",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 0},
                    "id": 200007,
                },
                {
                    **_lv("Rate limits (429)", Q_RATE_LIMIT, palette="white_on_yellow"),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 0},
                    "id": 200004,
                },
                {
                    **_lv(
                        "Bling 401 auto-renovado (ok)",
                        Q_BLING_AUTO,
                        palette="white_on_green",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 2},
                    "id": 200008,
                },
                {
                    **_lv(
                        "Renovacoes de Token ML",
                        'service:robo-markplaces "Token renovado"',
                        palette="white_on_green",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 2},
                    "id": 200003,
                },
                {
                    "definition": {
                        "title": "Top OAuth morto (por mensagem)",
                        "type": "toplist",
                        "requests": [
                            {
                                "conditional_formats": [
                                    {
                                        "comparator": ">",
                                        "palette": "white_on_red",
                                        "value": 0,
                                    }
                                ],
                                "formulas": [{"formula": "query1"}],
                                "queries": [
                                    {
                                        "compute": {"aggregation": "count"},
                                        "data_source": "logs",
                                        "group_by": [
                                            {
                                                "facet": "message",
                                                "limit": 10,
                                                "sort": {
                                                    "aggregation": "count",
                                                    "order": "desc",
                                                },
                                            }
                                        ],
                                        "indexes": ["*"],
                                        "name": "query1",
                                        "search": {"query": Q_OAUTH_MORTO},
                                    }
                                ],
                                "response_format": "scalar",
                            }
                        ],
                    },
                    "layout": {"height": 4, "width": 6, "x": 6, "y": 2},
                    "id": 200006,
                },
                {
                    "definition": {
                        "title": "OAuth morto por Marketplace",
                        "type": "timeseries",
                        "legend_columns": ["value", "sum"],
                        "legend_layout": "horizontal",
                        "show_legend": True,
                        "requests": [
                            {
                                "display_type": "bars",
                                "formulas": [{"formula": "query1"}],
                                "queries": [
                                    {
                                        "compute": {"aggregation": "count"},
                                        "data_source": "logs",
                                        "group_by": [
                                            {
                                                "facet": "marketplace",
                                                "limit": 10,
                                                "sort": {
                                                    "aggregation": "count",
                                                    "order": "desc",
                                                },
                                            }
                                        ],
                                        "indexes": ["*"],
                                        "name": "query1",
                                        "search": {"query": Q_OAUTH_MORTO},
                                    }
                                ],
                                "response_format": "timeseries",
                                "style": {"palette": "semantic"},
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 4},
                    "id": 200005,
                },
            ],
        },
        "layout": {"x": 0, "y": 0, "width": 12, "height": 1},
    }


def _grupo_pontos_cegos() -> dict[str, Any]:
    return {
        "id": GROUP_PONTOS_CEGOS_ID,
        "definition": {
            "title": "[Metricas] Chat / NF-e / Estoque / Telegram / Repricing",
            "type": "group",
            "background_color": "vivid_green",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv(
                        "Chat Rodadas",
                        "sum:robo.chat.rodadas{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 0},
                    "id": 720001,
                },
                {
                    **_qv(
                        "Chat Respondidas",
                        "sum:robo.chat.respondidas{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 0},
                    "id": 720002,
                },
                {
                    **_qv(
                        "Chat Falhas",
                        "sum:robo.chat.falha{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 0},
                    "id": 720003,
                },
                {
                    **_qv(
                        "NF-e Emitidas",
                        "sum:robo.nfe.emitida{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 0},
                    "id": 720004,
                },
                {
                    **_qv(
                        "NF-e Erros",
                        "sum:robo.nfe.erro{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 0},
                    "id": 720005,
                },
                {
                    **_qv(
                        "NF-e Dry-run",
                        "sum:robo.nfe.dry_run{*}.as_count()",
                        green_gt=None,
                        yellow_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 0},
                    "id": 720006,
                },
                {
                    **_qv(
                        "Estoque Rodadas",
                        "sum:robo.estoque.rodadas{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 2},
                    "id": 720007,
                },
                {
                    **_qv(
                        "Estoque Aplicado",
                        "sum:robo.estoque.aplicado{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 2},
                    "id": 720008,
                },
                {
                    **_qv(
                        "Telegram OK",
                        "sum:robo.telegram.envio_ok{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 2},
                    "id": 720009,
                },
                {
                    **_qv(
                        "Telegram Erro",
                        "sum:robo.telegram.envio_erro{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 2},
                    "id": 720010,
                },
                {
                    "id": 720011,
                    "definition": {
                        "title": "Chat / Estoque / Repricing / Telegram",
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
                                    {"alias": "Chat rodadas", "formula": "query1"},
                                    {"alias": "Estoque rodadas", "formula": "query2"},
                                    {"alias": "Repricing rodadas", "formula": "query3"},
                                    {"alias": "Telegram OK", "formula": "query4"},
                                    {"alias": "Telegram erro", "formula": "query5"},
                                ],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "sum:robo.chat.rodadas{*}.as_count()",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "sum:robo.estoque.rodadas{*}.as_count()",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query3",
                                        "query": "sum:robo.repricing.rodadas{*}.as_count()",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query4",
                                        "query": "sum:robo.telegram.envio_ok{*}.as_count()",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query5",
                                        "query": "sum:robo.telegram.envio_erro{*}.as_count()",
                                    },
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 8, "x": 0, "y": 4},
                },
                {
                    **_qv(
                        "Repricing Rodadas",
                        "sum:robo.repricing.rodadas{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 4},
                    "id": 720012,
                },
                {
                    **_qv(
                        "Repricing Aplicado",
                        "sum:robo.repricing.aplicado{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 4},
                    "id": 720013,
                },
                {
                    **_qv(
                        "Ads Rodadas",
                        "sum:robo.ads.rodadas{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 7},
                    "id": 720014,
                },
                {
                    **_qv(
                        "Ads Aplicado",
                        "sum:robo.ads.aplicado{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 7},
                    "id": 720015,
                },
                {
                    **_qv(
                        "Ads Falha",
                        "sum:robo.ads.falha{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 7},
                    "id": 720016,
                },
                {
                    **_qv(
                        "Vendas WA Notificadas",
                        "sum:robo.vendas.notificadas{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 7},
                    "id": 720017,
                },
                {
                    **_qv(
                        "Vendas WA Falha",
                        "sum:robo.vendas.falha_whatsapp{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 7},
                    "id": 720018,
                },
                {
                    **_qv(
                        "Ads Indisponivel 404",
                        "sum:robo.ads.indisponivel{*}.as_count()",
                        green_gt=None,
                        yellow_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 7},
                    "id": 720019,
                },
                {
                    **_qv(
                        "Estoque Falha",
                        "sum:robo.estoque.falha_aplicacao{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 9},
                    "id": 720020,
                },
                {
                    **_qv(
                        "Token Falha",
                        "sum:robo.token.falha{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 9},
                    "id": 720021,
                },
                {
                    **_qv(
                        "Repricing Falha",
                        "sum:robo.repricing.falha_aplicacao{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 9},
                    "id": 720022,
                },
                {
                    **_qv(
                        "Dados Degradado",
                        "sum:robo.dados.degradado{*}.as_count()",
                        green_gt=None,
                        yellow_gt=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 9},
                    "id": 720023,
                },
            ],
        },
        "layout": {"x": 0, "y": 20, "width": 12, "height": 1},
    }


def _grupo_catalogo_impala() -> dict[str, Any]:
    """Gauges do catálogo Impala (cruzamento cores × preço × margem)."""
    return {
        "id": GROUP_CATALOGO_IMPALA_ID,
        "definition": {
            "title": "[Catalogo Impala] Score / Margem / MLB / Guerra",
            "type": "group",
            "background_color": "vivid_orange",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv(
                        "Kits no catalogo",
                        "avg:robo.catalogo.kits_total{*}",
                        aggregator="avg",
                        green_gt=6,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 0},
                    "id": 730001,
                },
                {
                    **_qv(
                        "Guerra sem MLB",
                        "avg:robo.catalogo.guerra_sem_mlb{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 0},
                    "id": 730002,
                },
                {
                    **_qv(
                        "Guerra estoque zero",
                        "avg:robo.catalogo.guerra_estoque_zero{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 0},
                    "id": 730003,
                },
                {
                    **_qv(
                        "Kits sem MLB (todos)",
                        "avg:robo.catalogo.sem_mlb{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 0},
                    "id": 730004,
                },
                {
                    **_qv(
                        "P0 no catalogo",
                        "avg:robo.catalogo.kits_p0{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 0},
                    "id": 730005,
                },
                {
                    **_qv(
                        "P1 no catalogo",
                        "avg:robo.catalogo.kits_p1{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 0},
                    "id": 730006,
                },
                {
                    "id": 730010,
                    "definition": {
                        "title": "Margem trabalho vs real (por papel)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "legend_columns": ["avg", "value"],
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "style": {"palette": "datadog16"},
                                "formulas": [
                                    {"alias": "trabalho", "formula": "query1"},
                                    {"alias": "real", "formula": "query2"},
                                ],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": (
                                            "avg:robo.catalogo.margem_trabalho_pct{*} by {papel}"
                                        ),
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": (
                                            "avg:robo.catalogo.margem_real_pct{*} by {papel}"
                                        ),
                                    },
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 2},
                },
                {
                    "id": 730011,
                    "definition": {
                        "title": "Score alavancagem / vd_dia_ref (por papel)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "legend_columns": ["avg", "value"],
                        "requests": [
                            {
                                "display_type": "bars",
                                "response_format": "timeseries",
                                "style": {"palette": "datadog16"},
                                "formulas": [
                                    {"alias": "score", "formula": "query1"},
                                    {"alias": "vd/dia ref", "formula": "query2"},
                                ],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.catalogo.score{*} by {papel}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": (
                                            "avg:robo.catalogo.vd_dia_ref{*} by {papel}"
                                        ),
                                    },
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 2},
                },
                {
                    "id": 730012,
                    "definition": {
                        "title": "Gap % preco-alvo vs mercado (por papel)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "style": {"palette": "orange"},
                                "formulas": [{"alias": "gap % (alvo)", "formula": "query1"}],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": (
                                            "avg:robo.catalogo.gap_mercado_pct{*} by {papel}"
                                        ),
                                    },
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 5},
                },
                {
                    "id": 730013,
                    "definition": {
                        "title": "Preco-alvo F1 vs mercado (por papel)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "style": {"palette": "datadog16"},
                                "formulas": [
                                    {"alias": "preco", "formula": "query1"},
                                    {"alias": "mercado", "formula": "query2"},
                                ],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.catalogo.preco{*} by {papel}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": (
                                            "avg:robo.catalogo.preco_ml_mercado{*} by {papel}"
                                        ),
                                    },
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 5},
                },
            ],
        },
        "layout": {"x": 0, "y": 22, "width": 12, "height": 1},
    }


def _grupo_batalha_impala() -> dict[str, Any]:
    """Com quantos anúncios Impala lutamos + gap vs nossos preços."""
    return {
        "id": GROUP_BATALHA_IMPALA_ID,
        "definition": {
            "title": "[Batalha Impala] Concorrentes vs nossos kits",
            "type": "group",
            "background_color": "vivid_purple",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv(
                        "Anuncios Impala (amostra)",
                        "avg:robo.impala.batalha.anuncios_unicos{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 0},
                    "id": 740001,
                },
                {
                    **_qv(
                        "Sellers unicos",
                        "avg:robo.impala.batalha.sellers_unicos{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 0},
                    "id": 740002,
                },
                {
                    **_qv(
                        "Preco-alvo acima do rival",
                        "avg:robo.impala.batalha.nossos_acima_rival{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 0},
                    "id": 740003,
                },
                {
                    **_qv(
                        "Preco min Impala (amostra)",
                        "avg:robo.impala.batalha.preco_min{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 0},
                    "id": 740004,
                },
                {
                    "id": 740010,
                    "definition": {
                        "title": "Gap % preco-alvo vs rival min (por kit)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "style": {"palette": "cool"},
                                "formulas": [{"alias": "gap % (alvo)", "formula": "query1"}],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": (
                                            "avg:robo.impala.batalha.gap_vs_rival_pct{*} by {kit}"
                                        ),
                                    }
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 2},
                },
                {
                    "id": 740011,
                    "definition": {
                        "title": "Anuncios Impala por tamanho de kit",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "bars",
                                "response_format": "timeseries",
                                "style": {"palette": "datadog16"},
                                "formulas": [{"alias": "anuncios", "formula": "query1"}],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": (
                                            "avg:robo.impala.batalha.tam_anuncios{*} by {tam}"
                                        ),
                                    }
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 2},
                },
                {
                    "id": 740012,
                    "definition": {
                        "title": "Preco-alvo (catalogo) vs rival min (por kit)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "style": {"palette": "datadog16"},
                                "formulas": [
                                    {"alias": "preco-alvo", "formula": "query1"},
                                    {"alias": "rival min", "formula": "query2"},
                                ],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": (
                                            "avg:robo.impala.batalha.nosso_preco{*} by {kit}"
                                        ),
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": (
                                            "avg:robo.impala.batalha.rival_min{*} by {kit}"
                                        ),
                                    },
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 12, "x": 0, "y": 5},
                },
            ],
        },
        "layout": {"x": 0, "y": 24, "width": 12, "height": 1},
    }


def atualizar_dashboard_saude() -> None:
    raw = _get(f"/api/v1/dashboard/{DASH_SAUDE}")
    widgets = list(raw.get("widgets") or [])
    novo = []
    substituido = False
    tokens_ok = False
    catalogo_ok = False
    batalha_ok = False
    for w in widgets:
        d = w.get("definition") or {}
        title = d.get("title") if isinstance(d, dict) else None
        if w.get("id") == GROUP_PONTOS_CEGOS_ID or title == (
            "[Metricas] Chat / NF-e / Estoque / Telegram / Repricing"
        ):
            novo.append(_grupo_pontos_cegos())
            substituido = True
        elif w.get("id") == GROUP_TOKENS_ID or title == "Tokens e Autenticacao":
            grupo = _grupo_tokens()
            grupo["layout"] = w.get("layout") or grupo["layout"]
            novo.append(grupo)
            tokens_ok = True
        elif w.get("id") == GROUP_CATALOGO_IMPALA_ID or (
            isinstance(title, str) and title.startswith("[Catalogo Impala]")
        ):
            grupo = _grupo_catalogo_impala()
            grupo["layout"] = w.get("layout") or grupo["layout"]
            novo.append(grupo)
            catalogo_ok = True
        elif w.get("id") == GROUP_BATALHA_IMPALA_ID or (
            isinstance(title, str) and title.startswith("[Batalha Impala]")
        ):
            grupo = _grupo_batalha_impala()
            grupo["layout"] = w.get("layout") or grupo["layout"]
            novo.append(grupo)
            batalha_ok = True
        else:
            novo.append(w)
    if not substituido:
        novo.append(_grupo_pontos_cegos())
    if not tokens_ok:
        novo.insert(0, _grupo_tokens())
    if not catalogo_ok:
        novo.append(_grupo_catalogo_impala())
    if not batalha_ok:
        novo.append(_grupo_batalha_impala())

    payload = {
        "title": raw["title"],
        "description": (
            "Saude + pontos cegos + Catalogo Impala + Batalha Impala "
            "(anuncios rivais vs nossos kits). "
            "Orquestrador e Vigia em metricas; logs sem marketplace:*/componente:*."
        ),
        "widgets": novo,
        "layout_type": raw.get("layout_type") or "ordered",
        "template_variables": raw.get("template_variables") or [],
        "notify_list": raw.get("notify_list") or [],
        "reflow_type": raw.get("reflow_type"),
        "tags": raw.get("tags") or [],
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    _put(f"/api/v1/dashboard/{DASH_SAUDE}", payload)
    print(f"OK dashboard saude: https://us5.datadoghq.com/dashboard/{DASH_SAUDE}")


def _strip_cpu_ops_dashboard() -> None:
    """Remove widget irrelevante system.cpu.user do dashboard Ops (Actions sem host)."""
    try:
        raw = _get(f"/api/v1/dashboard/{DASH_OPS}")
    except Exception as exc:  # noqa: BLE001
        print(f"AVISO: nao leu dashboard Ops ({exc})")
        return

    def limpar(widgets: list[Any]) -> tuple[list[Any], int]:
        out: list[Any] = []
        removidos = 0
        for w in widgets:
            d = w.get("definition") or {}
            blob = json.dumps(d, ensure_ascii=False)
            if "system.cpu.user" in blob and d.get("type") != "group":
                removidos += 1
                continue
            if d.get("type") == "group" and isinstance(d.get("widgets"), list):
                filhos, r = limpar(d["widgets"])
                removidos += r
                d = {**d, "widgets": filhos}
                w = {**w, "definition": d}
            out.append(w)
        return out, removidos

    widgets, n = limpar(list(raw.get("widgets") or []))
    if n == 0:
        print("OK dashboard Ops: sem widget system.cpu.user (nada a remover)")
        return
    payload = {
        "title": raw["title"],
        "description": raw.get("description") or "",
        "widgets": widgets,
        "layout_type": raw.get("layout_type") or "ordered",
        "template_variables": raw.get("template_variables") or [],
        "notify_list": raw.get("notify_list") or [],
        "reflow_type": raw.get("reflow_type"),
        "tags": raw.get("tags") or [],
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    _put(f"/api/v1/dashboard/{DASH_OPS}", payload)
    print(f"OK dashboard Ops: removidos {n} widget(s) system.cpu.user")


def _monitores_desejados() -> list[dict[str, Any]]:
    msg_base = (
        "{{#is_alert}}Robo Marketplaces em alerta.{{/is_alert}}\n"
        "{{#is_recovery}}Recuperado.{{/is_recovery}}\n"
        f"Dashboard: https://us5.datadoghq.com/dashboard/{DASH_SAUDE}\n"
        "Tags: service:robo-markplaces"
    )
    return [
        {
            "name": "[Robo] Orquestrador sem ciclos (2h)",
            "type": "query alert",
            "query": "sum(last_2h):sum:robo.orquestrador.ciclo{*}.as_count() < 1",
            "message": (
                "Nenhum ciclo do orquestrador em 2h. "
                "Verifique GitHub Actions orquestrador_30min.\n" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:orquestrador", "severity:p2"],
            "options": {
                "thresholds": {"critical": 1},
                "notify_no_data": True,
                "no_data_timeframe": 150,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Vigia Datadog nao saudavel",
            "type": "query alert",
            "query": "avg(last_1h):avg:robo.vigia_datadog.saudavel{*} < 1",
            "message": (
                "Vigia reportou saude=0 (inatividades/erros abertos). "
                "Veja logs Vigia e fontes em catalogo/datadog_vigia_fontes.json.\n"
                + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:vigia", "severity:p2"],
            "options": {
                "thresholds": {"critical": 1},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Claude orcamento baixo (< US$2)",
            "type": "query alert",
            "query": "avg(last_30m):avg:robo.claude.orcamento_restante_usd{*} < 2",
            "message": (
                "Orcamento Claude abaixo de US$2. "
                "Revise CLAUDE_ATIVO / credito / economia_creditos.\n" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:claude", "severity:p3"],
            "options": {
                "thresholds": {"critical": 2},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 3,
        },
        {
            "name": "[Robo] Magalu auth/token (logs 1h)",
            "type": "log alert",
            "query": (
                'logs("service:robo-markplaces Magalu (401 OR invalid_grant)")'
                '.index("*").rollup("count").last("1h") > 5'
            ),
            "message": (
                "Magalu com falhas de autenticacao. "
                "Renove OAuth Magalu nos secrets do GitHub.\n" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:magalu", "severity:p1"],
            "options": {
                "thresholds": {"critical": 5},
                "enable_logs_sample": True,
                "notify_audit": False,
                "include_tags": True,
            },
            "priority": 1,
        },
        {
            "name": "[Robo] Telegram falhas de envio",
            "type": "query alert",
            "query": "sum(last_1h):sum:robo.telegram.envio_erro{*}.as_count() > 2",
            "message": (
                "Falhas no Telegram. Verifique TELEGRAM_TOKEN / chat_id "
                "(python scripts/diagnostico_telegram.py).\n" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:telegram", "severity:p2"],
            "options": {
                "thresholds": {"critical": 2},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] NF-e erros",
            "type": "query alert",
            "query": "sum(last_6h):sum:robo.nfe.erro{*}.as_count() > 2",
            "message": "Erros na emissao de NF-e (Bling). Revise faturamento/Lojahub.\n" + msg_base,
            "tags": [TAG_MONITOR, "monitor:nfe", "severity:p1"],
            "options": {
                "thresholds": {"critical": 2},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 1,
        },
        {
            "name": "[Robo] Estoque falha aplicacao",
            "type": "query alert",
            "query": "sum(last_6h):sum:robo.estoque.falha_aplicacao{*}.as_count() > 0",
            "message": "Falha ao aplicar estoque em canal. Risco de oversell/ruptura.\n" + msg_base,
            "tags": [TAG_MONITOR, "monitor:estoque", "severity:p1"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 1,
        },
        {
            "name": "[Robo] Token falha (OAuth)",
            "type": "query alert",
            "query": "sum(last_2h):sum:robo.token.falha{*}.as_count() > 0",
            "message": "Falha ao renovar/usar token OAuth. Verifique secrets.\n" + msg_base,
            "tags": [TAG_MONITOR, "monitor:token", "severity:p1"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 1,
        },
        {
            "name": "[Robo] Chat falhas",
            "type": "query alert",
            "query": "sum(last_2h):sum:robo.chat.falha{*}.as_count() > 3",
            "message": "Falhas ao responder chat (ML/Shopee/Magalu/Amazon).\n" + msg_base,
            "tags": [TAG_MONITOR, "monitor:chat", "severity:p2"],
            "options": {
                "thresholds": {"critical": 3},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Repricing falha aplicacao",
            "type": "query alert",
            "query": "sum(last_6h):sum:robo.repricing.falha_aplicacao{*}.as_count() > 0",
            "message": "Falha ao aplicar repricing. Margem/preco podem estar desatualizados.\n" + msg_base,
            "tags": [TAG_MONITOR, "monitor:repricing", "severity:p2"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Ads falha / probe",
            "type": "query alert",
            # So falha de escrita real. HTTP 404 de listagem/escopo Ads e config
            # conhecida e nao deve manter P1 em Alert permanente.
            # Nome mantido para upsert atualizar o monitor 21629780 existente.
            "query": "sum(last_24h):sum:robo.ads.falha{*}.as_count() > 0",
            "message": (
                "Falha ao aplicar Product Ads (escrita). "
                "404 de listagem/escopo NAO dispara este monitor — "
                "veja '[Robo] Product Ads indisponivel'.
" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:ads", "prioridad:p1"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 1,
        },
        {
            "name": "[Robo] Product Ads indisponivel (404/escopo)",
            "type": "query alert",
            "query": "sum(last_12h):sum:robo.ads.indisponivel{*}.as_count() > 0",
            "message": (
                "Product Ads ML retornou HTTP 404 (escopo advertising / advertiser). "
                "Corrija no DevCenter e regenere o token. "
                "Gatilho NAO pede aprovacao Telegram enquanto isto persistir.
" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:ads", "prioridad:p2"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Conectividade falhas",
            "type": "query alert",
            "query": "sum(last_2h):sum:robo.conectividade.falha{*}.as_count() > 5",
            "message": "Muitas falhas de conectividade marketplace.\n" + msg_base,
            "tags": [TAG_MONITOR, "monitor:conectividade", "severity:p2"],
            "options": {
                "thresholds": {"critical": 5},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Dados degradados",
            "type": "query alert",
            "query": "sum(last_2h):sum:robo.dados.degradado{*}.as_count() > 5",
            "message": "APIs retornando dados degradados/truncados.\n" + msg_base,
            "tags": [TAG_MONITOR, "monitor:dados", "severity:p3"],
            "options": {
                "thresholds": {"critical": 5},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 3,
        },
        {
            "name": "[Robo] Vendas WhatsApp busca falhou",
            "type": "query alert",
            "query": "sum(last_2h):sum:robo.vendas.busca_falhou{*}.as_count() > 0",
            "message": (
                "Busca de pedidos falhou (API generica) — vendas podem nao ser notificadas. "
                "Auth Magalu/invalid_grant NAO entra aqui (vai para busca_auth_quebrada + "
                "monitor Magalu).
" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:vendas", "prioridad:p1"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 1,
        },
        {
            "name": "[Robo] Vendas auth quebrada (OAuth)",
            "type": "query alert",
            "query": "sum(last_6h):sum:robo.vendas.busca_auth_quebrada{*}.as_count() > 0",
            "message": (
                "Busca de pedidos falhou por auth (401/403/invalid_grant). "
                "Renove OAuth do canal (tipicamente Magalu). "
                "Separado do P1 de busca generica.
" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:vendas", "prioridad:p2"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Brave cota esgotada",
            "type": "query alert",
            "query": "sum(last_1d):sum:robo.brave.quota_esgotada{*}.as_count() > 0",
            "message": (
                "Cota mensal Brave esgotada (hard-stop). "
                "Suba plano, BRAVE_QUOTA_MES, ou BRAVE_QUOTA_HARD_STOP=0.\n" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:brave", "severity:p2"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Brave HTTP 429",
            "type": "query alert",
            "query": "sum(last_6h):sum:robo.brave.http_429{*}.as_count() > 2",
            "message": "Brave Search retornou 429 (rate/cota). Verifique painel Brave.\n" + msg_base,
            "tags": [TAG_MONITOR, "monitor:brave", "severity:p2"],
            "options": {
                "thresholds": {"critical": 2},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Catalogo Impala guerra sem MLB",
            "type": "query alert",
            "query": "avg(last_1d):avg:robo.catalogo.guerra_sem_mlb{*} > 0",
            "message": (
                "SKU(s) de guerra Impala ainda sem MLB (MLB_PREENCHER). "
                "Publique PERL/VR/SORT antes de ads/promocao.\n" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:catalogo", "severity:p1"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 1,
        },
        {
            "name": "[Robo] Catalogo Impala margem real P0 baixa",
            "type": "query alert",
            "query": "avg(last_1d):avg:robo.catalogo.margem_real_pct{prio:p0} < 10",
            "message": (
                "Margem real media dos kits P0 abaixo de 10%. "
                "Revise preco F1 / Full / taxa vs custo_total.\n" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:catalogo", "severity:p2"],
            "options": {
                "thresholds": {"critical": 10},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
    ]


def upsert_monitores() -> None:
    existentes = _get("/api/v1/monitor")
    if not isinstance(existentes, list):
        existentes = existentes.get("monitors") or []
    por_nome = {str(m.get("name") or ""): m for m in existentes}

    for spec in _monitores_desejados():
        nome = spec["name"]
        body = {
            "name": nome,
            "type": spec["type"],
            "query": spec["query"],
            "message": spec["message"],
            "tags": spec["tags"],
            "options": spec["options"],
            "priority": spec.get("priority"),
        }
        atual = por_nome.get(nome)
        if atual and atual.get("id"):
            mid = atual["id"]
            _put(f"/api/v1/monitor/{mid}", body)
            print(f"OK monitor atualizado id={mid}: {nome}")
        else:
            created = _post("/api/v1/monitor", body)
            print(f"OK monitor criado id={created.get('id')}: {nome}")


def main() -> int:
    if not DD_API_KEY or not DD_APPLICATION_KEY:
        print("FALHA: DD_API_KEY e DD_APPLICATION_KEY obrigatorios no .env")
        return 1
    atualizar_dashboard_saude()
    _strip_cpu_ops_dashboard()
    upsert_monitores()
    print("Pronto. Monitores: https://us5.datadoghq.com/monitors/manage?q=tag%3Aservice%3Arobo-markplaces")
    print("Nota: OAuth Magalu continua manual (token invalid_grant nos logs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
