"""
Completa observabilidade Datadog do Robo Marketplaces:

1) Dashboard Robo/Saude (3iy-tka-awu): tokens, orquestrador, vigia, pontos cegos ops
2) Dashboard Fase 1 Impala / ML: catalogo, batalha, progresso Impala (sem Masterprint)
3) Dashboard Fase 2 Masterprint: progresso PETG + filamentos / escritorio
4) Monitores de alerta

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
# Preenchido em runtime (env DD_DASH_ECOMMERCE ou busca/cria pelo titulo).
DASH_ECOMMERCE = (os.getenv("DD_DASH_ECOMMERCE") or "j53-h48-8ea").strip()
DASH_ECOMMERCE_TITLE = "Robo Marketplaces - Fase 1 Ecommerce Impala / ML"
DASH_MASTERPRINT = (os.getenv("DD_DASH_MASTERPRINT") or "ggq-my7-h6g").strip()
DASH_MASTERPRINT_TITLE = "Robo Marketplaces - Fase 2 Masterprint Filamentos / Escritorio"
GROUP_PONTOS_CEGOS_ID = 700005
GROUP_TOKENS_ID = 100001
GROUP_CATALOGO_IMPALA_ID = 700006
GROUP_BATALHA_IMPALA_ID = 700007
GROUP_DECISAO_GUERRA_ID = 700018
GROUP_OPERACAO_COMERCIAL_ID = 700008
GROUP_MP_CATALOGO_ID = 760001
GROUP_MP_MERCADO_ID = 760002
GROUP_MP_COMERCIAL_ID = 760003
GROUP_MP_FUNIL_ID = 760004
GROUP_PROGRESSO_FASE2_ID = 760005
GROUP_PONTO_RUPTURA_ID = 700012
GROUP_SAUDE_CONTA_ML_ID = 700013
GROUP_RUPTURA_OUTRA_MARCA_ID = 700014
GROUP_MARCA_KIT_TENDENCIA_ID = 700015
GROUP_KITS_MANICURE_ID = 700016
GROUP_DECISAO_OSCILACAO_ID = 700017
GROUP_PROGRESSO_24M_ID = 700019
NOTE_ROBO_ID = 700009
NOTE_ECOM_ID = 700010
NOTE_MP_ID = 700011
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


def _ssl_verify() -> bool:
    return os.getenv("DD_SSL_VERIFY", "1").strip().lower() not in ("0", "false", "no")


def _get(path: str) -> Any:
    r = requests.get(_api(path), headers=_headers(), timeout=45, verify=_ssl_verify())
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict[str, Any]) -> Any:
    r = requests.post(
        _api(path), headers=_headers(), data=json.dumps(body), timeout=45, verify=_ssl_verify()
    )
    if r.status_code >= 300:
        raise RuntimeError(f"POST {path} HTTP {r.status_code}: {(r.text or '')[:800]}")
    return r.json()


def _put(path: str, body: dict[str, Any]) -> Any:
    r = requests.put(
        _api(path), headers=_headers(), data=json.dumps(body), timeout=60, verify=_ssl_verify()
    )
    if r.status_code >= 300:
        raise RuntimeError(f"PUT {path} HTTP {r.status_code}: {(r.text or '')[:800]}")
    return r.json() if r.text else {}


def _url_dash(dash_id: str) -> str:
    return f"https://{DD_SITE}/dashboard/{dash_id}"


def _note_widget(
    widget_id: int,
    content: str,
    *,
    background_color: str = "blue",
    height: int = 2,
) -> dict[str, Any]:
    return {
        "id": widget_id,
        "definition": {
            "type": "note",
            "content": content,
            "background_color": background_color,
            "font_size": "14",
            "text_align": "left",
            "show_tick": False,
            "tick_edge": "left",
            "tick_pos": "50%",
            "has_padding": True,
        },
        "layout": {"x": 0, "y": 0, "width": 12, "height": height},
    }


def _buscar_dashboard_por_titulo(titulo: str) -> str | None:
    raw = _get("/api/v1/dashboard")
    dashboards = raw.get("dashboards") if isinstance(raw, dict) else raw
    if not isinstance(dashboards, list):
        return None
    for d in dashboards:
        if not isinstance(d, dict):
            continue
        if str(d.get("title") or "").strip() == titulo:
            did = str(d.get("id") or "").strip()
            if did:
                return did
    return None


def _resolver_dash_ecommerce() -> str:
    """Retorna ID do dash Ecommerce (env, busca por titulo, ou cria vazio)."""
    global DASH_ECOMMERCE
    if DASH_ECOMMERCE:
        return DASH_ECOMMERCE
    existente = _buscar_dashboard_por_titulo(DASH_ECOMMERCE_TITLE)
    if existente:
        DASH_ECOMMERCE = existente
        return DASH_ECOMMERCE
    created = _post(
        "/api/v1/dashboard",
        {
            "title": DASH_ECOMMERCE_TITLE,
            "description": (
                "Fase 1 Impala / ML: catalogo, batalha de precos, ads e vendas. Sem Masterprint. "
                f"Robo/plataforma: {_url_dash(DASH_SAUDE)}"
            ),
            "widgets": [],
            "layout_type": "ordered",
        },
    )
    did = str(created.get("id") or "").strip()
    if not did:
        raise RuntimeError(f"Falha ao criar dashboard ecommerce: {created!r}")
    DASH_ECOMMERCE = did
    print(f"OK dashboard ecommerce CRIADO id={did}")
    return DASH_ECOMMERCE


def _resolver_dash_masterprint() -> str:
    """Retorna ID do dash Masterprint (filamentos + escritorio)."""
    global DASH_MASTERPRINT
    if DASH_MASTERPRINT:
        return DASH_MASTERPRINT
    existente = _buscar_dashboard_por_titulo(DASH_MASTERPRINT_TITLE)
    if existente:
        DASH_MASTERPRINT = existente
        return DASH_MASTERPRINT
    created = _post(
        "/api/v1/dashboard",
        {
            "title": DASH_MASTERPRINT_TITLE,
            "description": (
                "Fase 2 Masterprint: filamentos 3D, pinceis/apagadores, custos tabela "
                f"pedidos e mercado ML. Robo: {_url_dash(DASH_SAUDE)}"
            ),
            "widgets": [],
            "layout_type": "ordered",
        },
    )
    did = str(created.get("id") or "").strip()
    if not did:
        raise RuntimeError(f"Falha ao criar dashboard masterprint: {created!r}")
    DASH_MASTERPRINT = did
    print(f"OK dashboard masterprint CRIADO id={did}")
    return DASH_MASTERPRINT


def _eh_grupo_ecommerce(w: dict[str, Any]) -> bool:
    d = w.get("definition") or {}
    title = d.get("title") if isinstance(d, dict) else None
    wid = w.get("id")
    if wid in (
        GROUP_CATALOGO_IMPALA_ID,
        GROUP_BATALHA_IMPALA_ID,
        GROUP_OPERACAO_COMERCIAL_ID,
        GROUP_DECISAO_GUERRA_ID,
        GROUP_PROGRESSO_24M_ID,
    ):
        return True
    if isinstance(title, str) and (
        title.startswith("[Catalogo Impala]")
        or title.startswith("[Batalha Impala]")
        or title.startswith("[Operacao comercial]")
        or title.startswith("[Decisao guerra Impala]")
        or title.startswith("[Progresso 24 meses]")
        or title.startswith("[Fase 1 / Impala]")
    ):
        return True
    return False


def _eh_note_navegacao(w: dict[str, Any]) -> bool:
    return w.get("id") in (NOTE_ROBO_ID, NOTE_ECOM_ID, NOTE_MP_ID)


def _qv(
    title: str,
    query: str,
    *,
    aggregator: str = "sum",
    red_gt: float | None = None,
    red_lt: float | None = None,
    yellow_gt: float | None = None,
    yellow_lt: float | None = None,
    green_gt: float | None = 0,
    precision: int = 0,
) -> dict[str, Any]:
    formats: list[dict[str, Any]] = []
    if red_gt is not None:
        formats.append({"comparator": ">", "palette": "white_on_red", "value": red_gt})
    if red_lt is not None:
        formats.append({"comparator": "<", "palette": "white_on_red", "value": red_lt})
    if yellow_gt is not None:
        formats.append({"comparator": ">", "palette": "white_on_yellow", "value": yellow_gt})
    if yellow_lt is not None:
        formats.append({"comparator": "<", "palette": "white_on_yellow", "value": yellow_lt})
    if green_gt is not None:
        formats.append({"comparator": ">", "palette": "white_on_green", "value": green_gt})
    elif red_lt is None and yellow_gt is None and yellow_lt is None:
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


def _qv_formula(
    title: str,
    queries: list[tuple[str, str]],
    formula: str,
    *,
    aggregator: str = "avg",
    red_gt: float | None = None,
    red_lt: float | None = None,
    yellow_gt: float | None = None,
    yellow_lt: float | None = None,
    green_gt: float | None = 0,
    precision: int = 0,
) -> dict[str, Any]:
    """query_value com fórmula (ex.: lucro/mês ÷ meta × 100)."""
    formats: list[dict[str, Any]] = []
    if red_gt is not None:
        formats.append({"comparator": ">", "palette": "white_on_red", "value": red_gt})
    if red_lt is not None:
        formats.append({"comparator": "<", "palette": "white_on_red", "value": red_lt})
    if yellow_gt is not None:
        formats.append({"comparator": ">", "palette": "white_on_yellow", "value": yellow_gt})
    if yellow_lt is not None:
        formats.append({"comparator": "<", "palette": "white_on_yellow", "value": yellow_lt})
    if green_gt is not None:
        formats.append({"comparator": ">", "palette": "white_on_green", "value": green_gt})
    return {
        "definition": {
            "title": title,
            "type": "query_value",
            "autoscale": True,
            "precision": precision,
            "requests": [
                {
                    "conditional_formats": formats,
                    "formulas": [{"formula": formula}],
                    "queries": [
                        {
                            "data_source": "metrics",
                            "name": name,
                            "query": query,
                        }
                        for name, query in queries
                    ],
                    "response_format": "scalar",
                    "aggregator": aggregator,
                }
            ],
        }
    }


def _ts_overlay(
    title: str,
    series: list[tuple[str, str]],
    *,
    palette: str = "dog_classic",
) -> dict[str, Any]:
    """Timeseries com N séries (alias, query)."""
    queries = [
        {
            "data_source": "metrics",
            "name": f"query{i}",
            "query": query,
        }
        for i, (_alias, query) in enumerate(series, 1)
    ]
    formulas = [
        {"alias": alias, "formula": f"query{i}"}
        for i, (alias, _query) in enumerate(series, 1)
    ]
    return {
        "definition": {
            "title": title,
            "type": "timeseries",
            "show_legend": True,
            "legend_layout": "horizontal",
            "requests": [
                {
                    "display_type": "line",
                    "response_format": "timeseries",
                    "style": {"palette": palette},
                    "formulas": formulas,
                    "queries": queries,
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


def _toplist_metric(
    title: str,
    query: str,
    *,
    aggregator: str = "avg",
    order: str = "desc",
    limit: int = 10,
) -> dict[str, Any]:
    """Toplist de métrica (ex.: por kit / papel)."""
    return {
        "definition": {
            "title": title,
            "type": "toplist",
            "requests": [
                {
                    "formulas": [
                        {
                            "formula": "query1",
                            "limit": {"count": limit, "order": order},
                        }
                    ],
                    "queries": [
                        {
                            "data_source": "metrics",
                            "name": "query1",
                            "query": query,
                            "aggregator": aggregator,
                        }
                    ],
                    "response_format": "scalar",
                }
            ],
        }
    }


def _tabela_produto_catalogo() -> dict[str, Any]:
    """Tabela: produto (kit) × preço × custo × lucro × margem × vd/dia."""
    cols = [
        ("preco", "avg:robo.catalogo.preco{*} by {kit}", "Preco R$"),
        ("custo", "avg:robo.catalogo.custo_total{*} by {kit}", "Custo R$"),
        ("lucro", "avg:robo.catalogo.lucro_ref_ml{*} by {kit}", "Lucro ref R$"),
        ("margem", "avg:robo.catalogo.margem_real_pct{*} by {kit}", "Margem real %"),
        ("taxa", "avg:robo.catalogo.taxa_canal_pct{*} by {kit}", "Taxa canal %"),
        ("vd", "avg:robo.catalogo.vd_dia_ref{*} by {kit}", "VD/dia ref"),
    ]
    queries = []
    formulas = []
    for i, (name, q, alias) in enumerate(cols):
        queries.append(
            {
                "data_source": "metrics",
                "name": name,
                "query": q,
                "aggregator": "avg",
            }
        )
        formula: dict[str, Any] = {"alias": alias, "formula": name}
        if i == 0:
            formula["limit"] = {"count": 20, "order": "desc"}
        formulas.append(formula)
    return {
        "definition": {
            "title": "Produtos (kit) — preco / custo / lucro / margem / taxa / VD",
            "type": "query_table",
            "requests": [
                {
                    "queries": queries,
                    "formulas": formulas,
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
                                    {"alias": "Telegram P0 loja", "formula": "query6"},
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
                                    {
                                        "data_source": "metrics",
                                        "name": "query6",
                                        "query": "sum:robo.ml.loja.p0.telegram_ok{*}.as_count()",
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
                {
                    **_qv(
                        "P0 loja ativo (0/1)",
                        "avg:robo.ml.loja.p0.tem{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 11},
                    "id": 720024,
                },
                {
                    **_qv(
                        "Telegram P0 enviado",
                        "sum:robo.ml.loja.p0.telegram_ok{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 11},
                    "id": 720025,
                },
                {
                    **_qv(
                        "Telegram P0 skip",
                        "sum:robo.ml.loja.p0.telegram_skip{*}.as_count()",
                        green_gt=None,
                        yellow_gt=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 11},
                    "id": 720026,
                },
                {
                    **_qv(
                        "Briefing conta Telegram",
                        "sum:robo.ml.resumo_conta.telegram_ok{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 11},
                    "id": 720027,
                },
                {
                    **_qv(
                        "Meta Rodadas",
                        "sum:robo.meta.rodadas{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 13},
                    "id": 720028,
                },
                {
                    **_qv(
                        "Ciclo IG/FB pronto",
                        "avg:robo.meta.ciclo.pronto{*}",
                        aggregator="avg",
                        yellow_lt=1,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 13},
                    "id": 720029,
                },
                {
                    **_qv(
                        "Saude conta (ciclo)",
                        "avg:robo.ml.saude.conta_ok{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_lt=1,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 13},
                    "id": 720030,
                },
                {
                    **_qv(
                        "Impala ads ok",
                        "avg:robo.meta.ciclo.impala_ok{*}",
                        aggregator="avg",
                        yellow_lt=1,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 13},
                    "id": 720031,
                },
                {
                    **_qv(
                        "Campanhas IG",
                        "avg:robo.meta.campanhas_plataforma{plataforma:instagram}",
                        aggregator="avg",
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 13},
                    "id": 720032,
                },
                {
                    **_qv(
                        "Campanhas FB",
                        "avg:robo.meta.campanhas_plataforma{plataforma:facebook}",
                        aggregator="avg",
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 13},
                    "id": 720033,
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
                {
                    **_qv(
                        "AGIR: revisar preco",
                        "avg:robo.impala.batalha.agir_preco{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 8},
                    "id": 740020,
                },
                {
                    **_qv(
                        "AGIR: listing/Ads",
                        "avg:robo.impala.batalha.agir_listing{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 8},
                    "id": 740021,
                },
                {
                    **_qv(
                        "AGIR: publicar MLB",
                        "avg:robo.impala.batalha.agir_publicar_mlb{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 8},
                    "id": 740022,
                },
                {
                    **_qv(
                        "AGIR criticas",
                        "avg:robo.impala.batalha.agir_criticas{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 8},
                    "id": 740023,
                },
                {
                    **_qv(
                        "Gap mercado % (concorrentes)",
                        "avg:robo.mercado.gap_preco_pct{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=3,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 10},
                    "id": 740024,
                },
                {
                    **_qv(
                        "Conv. manicures leads",
                        "avg:robo.conversao_manicures.leads_novos{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 10},
                    "id": 740025,
                },
                {
                    **_qv(
                        "Conv. escrita pronta",
                        "avg:robo.conversao_manicures.escrita_pronta{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 10},
                    "id": 740026,
                },
                {
                    **_qv(
                        "Conv. ROAS real",
                        "avg:robo.conversao_manicures.roas_real{*}",
                        aggregator="avg",
                        green_gt=2,
                        yellow_gt=1,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 10},
                    "id": 740027,
                },
                {
                    **_qv(
                        "Maior seller Impala un/dia",
                        "avg:robo.impala.batalha.seller_vendas_dia_max{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 12},
                    "id": 740028,
                },
                {
                    **_qv(
                        "Sellers Impala no ranking",
                        "avg:robo.impala.batalha.top_sellers_emitidos{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 12},
                    "id": 740029,
                },
                {
                    **_qv(
                        "Amostra Impala com vendas/dia",
                        "avg:robo.impala.batalha.vendas_dia_amostra{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 12},
                    "id": 740030,
                },
                {
                    **_qv(
                        "Vendas proxy Impala (amostra)",
                        "avg:robo.impala.batalha.vendas_proxy{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 12},
                    "id": 740031,
                },
                {
                    **_toplist_metric(
                        "Maiores sellers Impala (un/dia)",
                        "avg:robo.impala.batalha.seller_vendas_dia{*} by {seller}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 14},
                    "id": 740032,
                },
                {
                    **_toplist_metric(
                        "Sellers Impala — anuncios na amostra",
                        "avg:robo.impala.batalha.seller_anuncios{*} by {seller}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 14},
                    "id": 740033,
                },
            ],
        },
        "layout": {"x": 0, "y": 24, "width": 12, "height": 1},
    }


def _grupo_decisao_guerra_impala() -> dict[str, Any]:
    """Margem operacional da frente + extras dos rivais (visão de atuação)."""
    return {
        "id": GROUP_DECISAO_GUERRA_ID,
        "definition": {
            "title": "[Decisao guerra Impala] Fase + MLB + margem/lucro catalogo + Cruzeiro + pipeline",
            "type": "group",
            "background_color": "vivid_orange",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv(
                        "Margem catalogo MIMO %",
                        "avg:robo.impala.guerra.margem_op_pct{kit:mimo003}",
                        aggregator="last",
                        green_gt=15,
                        yellow_lt=15,
                        red_lt=10,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 0},
                    "id": 741001,
                },
                {
                    **_qv(
                        "Margem catalogo PERL %",
                        "avg:robo.impala.guerra.margem_op_pct{kit:perl004}",
                        aggregator="last",
                        green_gt=15,
                        yellow_lt=15,
                        red_lt=10,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 0},
                    "id": 741002,
                },
                {
                    **_qv(
                        "Margem catalogo JUPAES %",
                        "avg:robo.impala.guerra.margem_op_pct{kit:jupaes006}",
                        aggregator="last",
                        green_gt=15,
                        yellow_lt=15,
                        red_lt=10,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 0},
                    "id": 741003,
                },
                {
                    **_qv(
                        "Rivais comparaveis (amostra viva)",
                        "avg:robo.impala.guerra.rivais_comparaveis{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 0},
                    "id": 741004,
                },
                {
                    "id": 741010,
                    "definition": {
                        "title": "Extras titulos (0 se cache velho / busca cega)",
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
                                        "query": "avg:robo.impala.guerra.extra_n{*} by {extra}",
                                    }
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 2},
                },
                {
                    "id": 741011,
                    "definition": {
                        "title": "Margem catalogo % (preco planejado, nao listing)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "style": {"palette": "cool"},
                                "formulas": [{"alias": "margem op %", "formula": "query1"}],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.impala.guerra.margem_op_pct{*} by {kit}",
                                    }
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 2},
                },
                {
                    **_qv(
                        "Nao comparaveis (amostra viva)",
                        "avg:robo.impala.guerra.rivais_nao_comparaveis{*}",
                        aggregator="last",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 5},
                    "id": 741020,
                },
                {
                    **_qv(
                        "Frente com MLB real (0-3)",
                        "avg:robo.impala.guerra.mlb_frente{*}",
                        aggregator="last",
                        green_gt=0,
                        red_lt=1,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 5},
                    "id": 741021,
                },
                {
                    **_qv(
                        "Cache busca idade h (amarelo >48h)",
                        "avg:robo.impala.guerra.cache_idade_h{*}",
                        aggregator="last",
                        green_gt=None,
                        yellow_gt=48,
                        red_gt=168,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 5},
                    "id": 741022,
                },
                {
                    **_qv(
                        "Mercado confiavel (0/1)",
                        "avg:robo.impala.guerra.mercado_confiavel{*}",
                        aggregator="last",
                        green_gt=0,
                        red_lt=1,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 5},
                    "id": 741023,
                },
                {
                    **_qv(
                        "Fase guerra 0-5 (0=abrir MIMO, nao e erro)",
                        "avg:robo.impala.guerra.fase{*}",
                        aggregator="last",
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 7},
                    "id": 741024,
                },
                {
                    **_qv(
                        "Liberar Ads (1 so na fase 3+)",
                        "avg:robo.impala.guerra.liberar_ads{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 7},
                    "id": 741025,
                },
                {
                    **_qv(
                        "Liberar golpe preco PERL (fase 4+)",
                        "avg:robo.impala.guerra.liberar_golpe_preco{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 7},
                    "id": 741026,
                },
                {
                    **_qv(
                        "Liberar ruptura (fase 5)",
                        "avg:robo.impala.guerra.liberar_ruptura{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 7},
                    "id": 741027,
                },
                {
                    **_qv(
                        "Publicar agora (gate MIMO, nao os 20 kits)",
                        "avg:robo.impala.guerra.publicar_agora{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 9},
                    "id": 741028,
                },
                {
                    **_qv(
                        "Kits catalogo acima piso 15%",
                        "avg:robo.catalogo.kits_acima_piso15{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 9},
                    "id": 741029,
                },
                {
                    **_qv(
                        "Lucro Cruzeiro spa R$/un",
                        "avg:robo.catalogo.lucro_ref_ml{kit:crzkit003}",
                        aggregator="last",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 9},
                    "id": 741030,
                },
                {
                    **_toplist_metric(
                        "Lucro ref R$/un por kit (maior = melhor capital)",
                        "avg:robo.catalogo.lucro_ref_ml{*} by {kit}",
                        aggregator="avg",
                        limit=8,
                    ),
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 11},
                    "id": 741032,
                },
                {
                    **_toplist_metric(
                        "Margem real % por kit (piso 15)",
                        "avg:robo.catalogo.margem_real_pct{*} by {kit}",
                        aggregator="avg",
                        limit=8,
                    ),
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 11},
                    "id": 741033,
                },
                {
                    **_toplist_metric(
                        "Pipeline onda 2+ lucro R$/un (nao publicar agora)",
                        "avg:robo.impala.pipeline.lucro_op{*} by {kit}",
                        aggregator="avg",
                        limit=8,
                    ),
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 14},
                    "id": 741034,
                },
                {
                    **_toplist_metric(
                        "Pipeline onda 2+ margem op %",
                        "avg:robo.impala.pipeline.margem_op_pct{*} by {kit}",
                        aggregator="avg",
                        limit=8,
                    ),
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 14},
                    "id": 741035,
                },
                {
                    **_qv(
                        "Titulo MIMO atracao (Impala+esmalte+Carmed+manicure)",
                        "avg:robo.impala.guerra.titulo_atracao{*}",
                        aggregator="last",
                        green_gt=0,
                        red_lt=1,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 17},
                    "id": 741036,
                },
                {
                    **_qv(
                        "Carmed no titulo catalogo (0/1)",
                        "avg:robo.impala.guerra.carmed_titulo{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 17},
                    "id": 741037,
                },
                {
                    **_qv(
                        "Carmed no ar (MLB + titulo)",
                        "avg:robo.impala.guerra.nosso_carmed{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 17},
                    "id": 741038,
                },
                {
                    **_qv(
                        "MIMO entrada manicure (extra, nao economia)",
                        "avg:robo.esmaltes.kit_manicure.entrada_ok{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 17},
                    "id": 741039,
                },
                {
                    **_qv(
                        "Canal ML liberado (referente)",
                        "avg:robo.impala.guerra.canal_liberado{marketplace:mercadolivre}",
                        aggregator="last",
                        green_gt=0,
                        red_lt=1,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 19},
                    "id": 741040,
                },
                {
                    **_qv(
                        "Canal Shopee (so apos fase 3 ML)",
                        "avg:robo.impala.guerra.canal_liberado{marketplace:shopee}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 19},
                    "id": 741041,
                },
                {
                    **_qv(
                        "Canal Magalu (so apos fase 3 ML)",
                        "avg:robo.impala.guerra.canal_liberado{marketplace:magalu}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 19},
                    "id": 741042,
                },
                {
                    **_qv(
                        "Canal Amazon (so apos fase 3 ML)",
                        "avg:robo.impala.guerra.canal_liberado{marketplace:amazon}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 19},
                    "id": 741043,
                },
                {
                    **_qv(
                        "Maior seller Cruzeiro un/dia",
                        "avg:robo.cruzeiro.mercado.seller_vendas_dia_max{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 4, "x": 0, "y": 21},
                    "id": 741044,
                },
                {
                    **_qv(
                        "Sellers Cruzeiro no ranking",
                        "avg:robo.cruzeiro.mercado.top_sellers_emitidos{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 4, "x": 4, "y": 21},
                    "id": 741045,
                },
                {
                    **_qv(
                        "Amostra Cruzeiro com vendas/dia",
                        "avg:robo.cruzeiro.mercado.vendas_dia_amostra{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 4, "x": 8, "y": 21},
                    "id": 741046,
                },
                {
                    **_toplist_metric(
                        "Maiores sellers Cruzeiro (un/dia)",
                        "avg:robo.cruzeiro.mercado.seller_vendas_dia{*} by {seller}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 23},
                    "id": 741047,
                },
                {
                    **_toplist_metric(
                        "Sellers Cruzeiro — anuncios na amostra",
                        "avg:robo.cruzeiro.mercado.seller_anuncios{*} by {seller}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 23},
                    "id": 741048,
                },
                {
                    **_qv(
                        "Momento IG/FB no ciclo (1=saude ML + Impala ads)",
                        "avg:robo.meta.ciclo.pronto{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 26},
                    "id": 741049,
                },
                {
                    **_qv(
                        "Saude conta ML (gate IG/FB)",
                        "avg:robo.meta.ciclo.saude_conta_ok{*}",
                        aggregator="last",
                        green_gt=0,
                        red_lt=1,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 26},
                    "id": 741050,
                },
                {
                    **_qv(
                        "Impala ads-ready fase 3+ (gate IG/FB)",
                        "avg:robo.meta.ciclo.impala_ok{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 26},
                    "id": 741051,
                },
                {
                    **_qv(
                        "Meta campanhas (0 ate ligar)",
                        "avg:robo.meta.campanhas_total{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 26},
                    "id": 741052,
                },
                {
                    **_qv(
                        "Campanhas Instagram",
                        "avg:robo.meta.campanhas_plataforma{plataforma:instagram}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 26},
                    "id": 741053,
                },
                {
                    **_qv(
                        "Campanhas Facebook",
                        "avg:robo.meta.campanhas_plataforma{plataforma:facebook}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 26},
                    "id": 741054,
                },
                {
                    **_qv(
                        "ROAS real ML/Ads (receita ML / gasto Meta)",
                        "avg:robo.meta.ciclo.roas_real{*}",
                        aggregator="last",
                        green_gt=2.1,
                        yellow_gt=1.0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 28},
                    "id": 741055,
                },
                {
                    **_qv(
                        "ROAS pixel Meta",
                        "avg:robo.meta.ciclo.roas_pixel{*}",
                        aggregator="last",
                        green_gt=2.1,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 28},
                    "id": 741056,
                },
                {
                    **_qv(
                        "Receita ML R$ (periodo)",
                        "avg:robo.meta.ciclo.receita_ml{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 28},
                    "id": 741057,
                },
                {
                    **_qv(
                        "Pedidos ML (periodo)",
                        "avg:robo.meta.ciclo.pedidos_ml{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 28},
                    "id": 741058,
                },
                {
                    **_qv(
                        "CPA ML R$ (gasto / pedido)",
                        "avg:robo.meta.ciclo.cpa_ml{*}",
                        aggregator="last",
                        green_gt=None,
                        yellow_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 28},
                    "id": 741059,
                },
                {
                    **_qv(
                        "Conv. impressao → pedido ML %",
                        "avg:robo.meta.ciclo.conversao_imp_pct{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=3,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 28},
                    "id": 741060,
                },
                {
                    **_qv(
                        "Eficiencia Ads×ML % (ROAS/meta)",
                        "avg:robo.meta.ciclo.eficiencia_pct{*}",
                        aggregator="last",
                        green_gt=99,
                        yellow_gt=49,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 30},
                    "id": 741061,
                },
                {
                    **_qv(
                        "Cobertura R$ (ML - gasto Ads)",
                        "avg:robo.meta.ciclo.cobertura_reais{*}",
                        aggregator="last",
                        green_gt=0,
                        red_lt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 30},
                    "id": 741062,
                },
                {
                    **_qv(
                        "Conv. clique → pedido ML %",
                        "avg:robo.meta.ciclo.conversao_click_pct{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 30},
                    "id": 741063,
                },
                {
                    **_qv(
                        "Ticket medio ML R$",
                        "avg:robo.meta.ciclo.ticket_ml{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 30},
                    "id": 741064,
                },
                {
                    **_qv(
                        "Impressoes Meta",
                        "avg:robo.meta.ciclo.impressoes{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 30},
                    "id": 741065,
                },
                {
                    **_qv(
                        "Status Ads×ML (0=sem dado 1=ok 2=alerta 3=critico)",
                        "avg:robo.meta.ciclo.status_num{*}",
                        aggregator="last",
                        green_gt=None,
                        yellow_gt=1.5,
                        red_gt=2.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 30},
                    "id": 741066,
                },
            ],
        },
        "layout": {"x": 0, "y": 26, "width": 12, "height": 1},
    }


def _grupo_operacao_comercial() -> dict[str, Any]:
    """Vendas/lucro em destaque + ads + decisao (leitura comercial)."""
    lucro_qv = {
        "definition": {
            "title": "Lucro R$ (periodo)",
            "type": "query_value",
            "autoscale": True,
            "precision": 2,
            "requests": [
                {
                    "conditional_formats": [
                        {"comparator": ">", "palette": "white_on_green", "value": 0},
                        {"comparator": "<", "palette": "white_on_red", "value": 0},
                        {"comparator": "=", "palette": "white_on_yellow", "value": 0},
                    ],
                    "formulas": [{"formula": "query1"}],
                    "queries": [
                        {
                            "data_source": "metrics",
                            "name": "query1",
                            "query": "sum:robo.vendas.lucro_reais{*}",
                        }
                    ],
                    "response_format": "scalar",
                    "aggregator": "sum",
                }
            ],
        }
    }
    return {
        "id": GROUP_OPERACAO_COMERCIAL_ID,
        "definition": {
            "title": "[Operacao comercial] Vendas / Lucro / Ads / Decisao",
            "type": "group",
            "background_color": "vivid_orange",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                # --- Vendas e lucro (primeira leitura) ---
                {
                    **_qv(
                        "Receita bruta R$",
                        "sum:robo.vendas.receita_bruta{*}",
                        aggregator="sum",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 0},
                    "id": 750030,
                },
                {
                    **lucro_qv,
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 0},
                    "id": 750031,
                },
                {
                    **_qv(
                        "Margem media vendas %",
                        "avg:robo.vendas.margem_media_pct{*}",
                        aggregator="avg",
                        green_gt=15,
                        yellow_gt=10,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 0},
                    "id": 750032,
                },
                {
                    **_qv(
                        "Lucro ref ML (catalogo)",
                        "sum:robo.catalogo.lucro_ref_ml{*}",
                        aggregator="sum",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 0},
                    "id": 750033,
                },
                {
                    **_qv(
                        "Margem trabalho %",
                        "avg:robo.catalogo.margem_trabalho_pct{*}",
                        aggregator="avg",
                        green_gt=15,
                        yellow_gt=10,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 0},
                    "id": 750034,
                },
                {
                    **_qv(
                        "Margem real % (pos taxas)",
                        "avg:robo.catalogo.margem_real_pct{*}",
                        aggregator="avg",
                        green_gt=10,
                        yellow_gt=5,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 0},
                    "id": 750035,
                },
                {
                    "id": 750040,
                    "definition": {
                        "title": "Receita vs lucro (R$)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "style": {"palette": "dog_classic"},
                                "formulas": [
                                    {"alias": "receita", "formula": "query1"},
                                    {"alias": "lucro", "formula": "query2"},
                                ],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "sum:robo.vendas.receita_bruta{*}.rollup(sum, 3600)",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "sum:robo.vendas.lucro_reais{*}.rollup(sum, 3600)",
                                    },
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 2},
                },
                {
                    "id": 750041,
                    "definition": {
                        "title": "Margem % (vendas vs catalogo)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "style": {"palette": "cool"},
                                "formulas": [
                                    {"alias": "margem vendas", "formula": "query1"},
                                    {"alias": "margem trabalho", "formula": "query2"},
                                    {"alias": "margem real", "formula": "query3"},
                                ],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.vendas.margem_media_pct{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "avg:robo.catalogo.margem_trabalho_pct{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query3",
                                        "query": "avg:robo.catalogo.margem_real_pct{*}",
                                    },
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 2},
                },
                # --- Custo / investimento / crescimento ---
                {
                    **_qv(
                        "Custo investido (catalogo)",
                        "avg:robo.catalogo.custo_investido{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 5},
                    "id": 750050,
                },
                {
                    **_qv(
                        "Custo vendas (COGS) R$",
                        "sum:robo.vendas.custo_total{*}",
                        aggregator="sum",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 5},
                    "id": 750051,
                },
                {
                    **_qv(
                        "Investimento Ads R$/dia",
                        "avg:robo.ads.budget_sugerido{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 5},
                    "id": 750052,
                },
                {
                    **_qv(
                        "Taxa crescimento kits % receita",
                        "avg:robo.crescimento_esmaltes.kits_pct{*}",
                        aggregator="avg",
                        green_gt=40,
                        yellow_gt=25,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 5},
                    "id": 750053,
                },
                {
                    **_qv(
                        "VD/dia ref (crescimento)",
                        "sum:robo.catalogo.vd_dia_ref{*}",
                        aggregator="sum",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 5},
                    "id": 750054,
                },
                {
                    **_qv(
                        "Taxa canal media %",
                        "avg:robo.catalogo.taxa_canal_pct{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=16,
                        red_gt=20,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 5},
                    "id": 750055,
                },
                {
                    **_qv(
                        "Invest. validacao total R$",
                        "avg:robo.catalogo.invest_validacao_total{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 7},
                    "id": 750070,
                },
                {
                    **_qv(
                        "Kits no plano validacao",
                        "avg:robo.catalogo.plano_validacao_kits{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 7},
                    "id": 750071,
                },
                {
                    **_qv(
                        "Kits Cruzeiro (validar)",
                        "avg:robo.cruzeiro.kits_validacao{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 7},
                    "id": 750072,
                },
                {
                    **_qv(
                        "Margem media Cruzeiro %",
                        "avg:robo.cruzeiro.margem_media_pct{*}",
                        aggregator="avg",
                        green_gt=25,
                        yellow_gt=15,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 7},
                    "id": 750073,
                },
                {
                    **_qv(
                        "Oportunidades Impala",
                        "avg:robo.catalogo.oportunidades_impala{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 7},
                    "id": 750074,
                },
                {
                    **_qv(
                        "Complementos Livia",
                        "avg:robo.catalogo.complementos_livia{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 7},
                    "id": 750075,
                },
                # --- Produto x valores ---
                {
                    **_tabela_produto_catalogo(),
                    "layout": {"height": 4, "width": 12, "x": 0, "y": 9},
                    "id": 750060,
                },
                {
                    **_toplist_metric(
                        "Invest. validacao por kit R$",
                        "avg:robo.catalogo.invest_validacao{*} by {kit}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 0, "y": 13},
                    "id": 750076,
                },
                {
                    **_toplist_metric(
                        "Margem Cruzeiro % por kit",
                        "avg:robo.cruzeiro.margem_pct{*} by {kit}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 4, "y": 13},
                    "id": 750077,
                },
                {
                    **_toplist_metric(
                        "Lucro Cruzeiro R$ por kit",
                        "avg:robo.cruzeiro.lucro_ref{*} by {kit}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 8, "y": 13},
                    "id": 750078,
                },
                {
                    **_toplist_metric(
                        "Receita por produto (kit)",
                        "sum:robo.vendas.receita_por_kit{*} by {kit}",
                        aggregator="sum",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 0, "y": 16},
                    "id": 750061,
                },
                {
                    **_toplist_metric(
                        "Lucro por produto (kit)",
                        "sum:robo.vendas.lucro_por_kit{*} by {kit}",
                        aggregator="sum",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 4, "y": 16},
                    "id": 750062,
                },
                {
                    **_toplist_metric(
                        "Custo por produto (kit)",
                        "sum:robo.vendas.custo_por_kit{*} by {kit}",
                        aggregator="sum",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 8, "y": 16},
                    "id": 750063,
                },
                {
                    **_toplist_metric(
                        "VD/dia por produto (kit)",
                        "avg:robo.catalogo.vd_dia_ref{*} by {kit}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 0, "y": 19},
                    "id": 750064,
                },
                {
                    **_toplist_metric(
                        "Custo unitario por produto",
                        "avg:robo.catalogo.custo_total{*} by {kit}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 4, "y": 19},
                    "id": 750065,
                },
                {
                    **_toplist_metric(
                        "Lucro ref ML por produto",
                        "avg:robo.catalogo.lucro_ref_ml{*} by {kit}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 8, "y": 19},
                    "id": 750066,
                },
                # --- Ads ---
                {
                    **_qv("Ads Rodadas", "sum:robo.ads.rodadas{*}.as_count()"),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 22},
                    "id": 750001,
                },
                {
                    **_qv("Ads Aplicado", "sum:robo.ads.aplicado{*}.as_count()"),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 22},
                    "id": 750002,
                },
                {
                    **_qv(
                        "Ads Falha",
                        "sum:robo.ads.falha{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 22},
                    "id": 750003,
                },
                {
                    **_qv(
                        "Ads Indisponivel 404",
                        "sum:robo.ads.indisponivel{*}.as_count()",
                        green_gt=None,
                        yellow_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 22},
                    "id": 750004,
                },
                {
                    **_qv(
                        "ACOS atual",
                        "avg:robo.ads.acos_atual{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0.15,
                        red_gt=0.25,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 22},
                    "id": 750005,
                },
                {
                    **_qv(
                        "Budget sugerido",
                        "avg:robo.ads.budget_sugerido{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 22},
                    "id": 750006,
                },
                {
                    **_qv(
                        "Ads probe falha",
                        "sum:robo.ads.probe_falha{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 24},
                    "id": 750007,
                },
                # --- Alertas de canal + decisao ---
                {
                    **_qv(
                        "Vendas WA Notificadas",
                        "sum:robo.vendas.notificadas{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 26},
                    "id": 750010,
                },
                {
                    **_qv(
                        "Vendas busca falhou",
                        "sum:robo.vendas.busca_falhou{*}.as_count()",
                        green_gt=None,
                        red_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 26},
                    "id": 750011,
                },
                {
                    **_qv(
                        "Vendas auth quebrada",
                        "sum:robo.vendas.busca_auth_quebrada{*}.as_count()",
                        green_gt=None,
                        yellow_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 26},
                    "id": 750012,
                },
                {
                    **_qv(
                        "Itens analisados (margem)",
                        "sum:robo.vendas.itens_analisados{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 26},
                    "id": 750014,
                },
                {
                    **_qv(
                        "Ecossistema score",
                        "avg:robo.ecossistema_esmaltes.score{*}",
                        aggregator="avg",
                        green_gt=70,
                        yellow_gt=50,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 26},
                    "id": 750013,
                },
                {
                    **_qv(
                        "Crescimento margem %",
                        "avg:robo.crescimento_esmaltes.margem_pct{*}",
                        aggregator="avg",
                        green_gt=15,
                        yellow_gt=10,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 26},
                    "id": 750015,
                },
                {
                    **_qv(
                        "Decisao liberados",
                        "avg:robo.decisao_dia_esmaltes.liberados{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 28},
                    "id": 750020,
                },
                {
                    **_qv(
                        "Decisao bloqueados",
                        "avg:robo.decisao_dia_esmaltes.bloqueados{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 28},
                    "id": 750021,
                },
                {
                    **_qv(
                        "Kits sem MLB (crescimento)",
                        "avg:robo.crescimento_esmaltes.kits_sem_mlb{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 28},
                    "id": 750022,
                },
            ],
        },
        "layout": {"x": 0, "y": 0, "width": 12, "height": 1},
    }


def _grupo_catalogo_masterprint() -> dict[str, Any]:
    """Custos/SKUs da TABELA DE PEDIDOS (filamentos + escritorio)."""
    return {
        "id": GROUP_MP_CATALOGO_ID,
        "definition": {
            "title": "[Fase 2 · Catalogo Masterprint] Filamentos / Pinceis / Apagadores",
            "type": "group",
            "background_color": "vivid_blue",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv(
                        "SKUs tabela (foco)",
                        "avg:robo.masterprint.tabela.skus{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 0},
                    "id": 760101,
                },
                {
                    **_qv(
                        "SKUs filamentos",
                        "avg:robo.masterprint.tabela.filamentos_skus{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 0},
                    "id": 760102,
                },
                {
                    **_qv(
                        "SKUs escritorio",
                        "avg:robo.masterprint.tabela.escritorio_skus{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 0},
                    "id": 760103,
                },
                {
                    **_qv(
                        "Custo invest. filamentos",
                        "avg:robo.masterprint.tabela.custo_investido_filamentos{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 0},
                    "id": 760104,
                },
                {
                    **_qv(
                        "Custo invest. escritorio",
                        "avg:robo.masterprint.tabela.custo_investido_escritorio{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 0},
                    "id": 760105,
                },
                {
                    **_toplist_metric(
                        "SKUs por material",
                        "avg:robo.masterprint.tabela.skus_material{*} by {material}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 0, "y": 2},
                    "id": 760110,
                },
                {
                    **_toplist_metric(
                        "Custo medio R$ por material",
                        "avg:robo.masterprint.tabela.custo_medio{*} by {material}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 4, "y": 2},
                    "id": 760111,
                },
                {
                    **_toplist_metric(
                        "Custo min R$ por material",
                        "avg:robo.masterprint.tabela.custo_min{*} by {material}",
                        aggregator="avg",
                        order="asc",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 8, "y": 2},
                    "id": 760112,
                },
            ],
        },
        "layout": {"x": 0, "y": 0, "width": 12, "height": 1},
    }


def _grupo_funil_demanda_masterprint() -> dict[str, Any]:
    """Funil próprio (visitas→vendas) + ações + blindspots + visitas rivais."""
    return {
        "id": GROUP_MP_FUNIL_ID,
        "definition": {
            "title": "[Fase 2 · Funil ML] Visitas → vendas / acoes / blindspots",
            "type": "group",
            "background_color": "vivid_green",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    "id": 760400,
                    "definition": {
                        "type": "note",
                        "content": (
                            "**Funil próprio** = visitas e pedidos da *sua* conta "
                            "(taxa ≈ un./visitas). "
                            "**Visitas rivais** = proxy de demanda (sem vendas). "
                            "**Ações críticas** = visitas sem conversão / conversão baixa → "
                            "otimizador_listing prioriza esses IDs.\n"
                            "Blindspot vendas API = 1 enquanto `sold_quantity` de rivais = 403.\n"
                            "`blindspot.cegos` = quantos gaps estruturais (busca 403, claims, reviews…).\n"
                            "Métricas `*.funil.*` / `*.blindspot.*` aparecem após a 1ª rodada "
                            "dos monitores PETG / Filamentos com o código novo."
                        ),
                        "background_color": "green",
                        "font_size": "14",
                        "text_align": "left",
                        "show_tick": False,
                        "has_padding": True,
                    },
                    "layout": {"height": 2, "width": 12, "x": 0, "y": 0},
                },
                {
                    **_qv(
                        "PETG funil visitas 7d",
                        "avg:robo.masterprint_petg.funil.visitas_7d{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 2},
                    "id": 760401,
                },
                {
                    **_qv(
                        "PETG un. convertidas 7d",
                        "avg:robo.masterprint_petg.funil.unidades_7d{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 2},
                    "id": 760402,
                },
                {
                    **_qv(
                        "PETG conversao %",
                        "avg:robo.masterprint_petg.funil.conversao_pct{*}",
                        aggregator="avg",
                        green_gt=2,
                        yellow_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 2},
                    "id": 760403,
                },
                {
                    **_qv(
                        "PETG acoes criticas",
                        "avg:robo.masterprint_petg.funil.acoes_criticas{*}",
                        aggregator="avg",
                        red_gt=0,
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 2},
                    "id": 760404,
                },
                {
                    **_qv(
                        "PETG visitas rivais (amostra)",
                        "avg:robo.masterprint_petg.rivais.visitas_amostra{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 2},
                    "id": 760405,
                },
                {
                    **_qv(
                        "PETG blindspot vendas API",
                        "avg:robo.masterprint_petg.blindspot.vendas_api{*}",
                        aggregator="avg",
                        yellow_gt=0,
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 2},
                    "id": 760406,
                },
                {
                    **_qv(
                        "Filamentos funil visitas 7d",
                        "avg:robo.filamentos.ml.funil.visitas_7d{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 4},
                    "id": 760410,
                },
                {
                    **_qv(
                        "Filamentos un. 7d",
                        "avg:robo.filamentos.ml.funil.unidades_7d{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 4},
                    "id": 760411,
                },
                {
                    **_qv(
                        "Filamentos conversao %",
                        "avg:robo.filamentos.ml.funil.conversao_pct{*}",
                        aggregator="avg",
                        green_gt=2,
                        yellow_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 4},
                    "id": 760412,
                },
                {
                    **_qv(
                        "Filamentos acoes criticas",
                        "avg:robo.filamentos.ml.funil.acoes_criticas{*}",
                        aggregator="avg",
                        red_gt=0,
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 4},
                    "id": 760413,
                },
                {
                    **_qv(
                        "Filamentos visitas rivais",
                        "avg:robo.filamentos.ml.rivais.visitas_amostra{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 4},
                    "id": 760414,
                },
                {
                    **_qv(
                        "Filamentos blindspot vendas",
                        "avg:robo.filamentos.ml.blindspot.vendas_api{*}",
                        aggregator="avg",
                        yellow_gt=0,
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 4},
                    "id": 760415,
                },
                {
                    "id": 760420,
                    "definition": {
                        "title": "PETG — funil visitas / un. / conversao %",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.masterprint_petg.funil.visitas_7d{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "avg:robo.masterprint_petg.funil.unidades_7d{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query3",
                                        "query": "avg:robo.masterprint_petg.funil.conversao_pct{*}",
                                    },
                                ],
                                "formulas": [
                                    {"alias": "visitas_7d", "formula": "query1"},
                                    {"alias": "unidades_7d", "formula": "query2"},
                                    {"alias": "conversao_pct", "formula": "query3"},
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 6},
                },
                {
                    "id": 760421,
                    "definition": {
                        "title": "Filamentos — funil visitas / un. / conversao %",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.filamentos.ml.funil.visitas_7d{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "avg:robo.filamentos.ml.funil.unidades_7d{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query3",
                                        "query": "avg:robo.filamentos.ml.funil.conversao_pct{*}",
                                    },
                                ],
                                "formulas": [
                                    {"alias": "visitas_7d", "formula": "query1"},
                                    {"alias": "unidades_7d", "formula": "query2"},
                                    {"alias": "conversao_pct", "formula": "query3"},
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 6},
                },
                {
                    "id": 760430,
                    "definition": {
                        "title": "Acoes funil — criticas / total (PETG + Filamentos)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "bars",
                                "response_format": "timeseries",
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.masterprint_petg.funil.acoes_criticas{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "avg:robo.filamentos.ml.funil.acoes_criticas{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query3",
                                        "query": "avg:robo.masterprint_petg.funil.acoes_total{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query4",
                                        "query": "avg:robo.filamentos.ml.funil.acoes_total{*}",
                                    },
                                ],
                                "formulas": [
                                    {"alias": "petg_criticas", "formula": "query1"},
                                    {"alias": "fil_criticas", "formula": "query2"},
                                    {"alias": "petg_total", "formula": "query3"},
                                    {"alias": "fil_total", "formula": "query4"},
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 9},
                },
                {
                    "id": 760431,
                    "definition": {
                        "title": "Acoes por tipo (PETG) — baixar_preco / titulo_ads / conversao",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "bars",
                                "response_format": "timeseries",
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": (
                                            "avg:robo.masterprint_petg.funil.acao."
                                            "baixar_preco_ou_listing{*}"
                                        ),
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": (
                                            "avg:robo.masterprint_petg.funil.acao."
                                            "melhorar_titulo_e_ads{*}"
                                        ),
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query3",
                                        "query": (
                                            "avg:robo.masterprint_petg.funil.acao."
                                            "melhorar_conversao_listing{*}"
                                        ),
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query4",
                                        "query": (
                                            "avg:robo.masterprint_petg.funil.acao."
                                            "republicar_ou_ads{*}"
                                        ),
                                    },
                                ],
                                "formulas": [
                                    {"alias": "baixar_preco", "formula": "query1"},
                                    {"alias": "titulo_ads", "formula": "query2"},
                                    {"alias": "conversao_listing", "formula": "query3"},
                                    {"alias": "republicar_ads", "formula": "query4"},
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 9},
                },
                {
                    **_qv(
                        "PETG blindspots cegos",
                        "avg:robo.masterprint_petg.blindspot.cegos{*}",
                        aggregator="avg",
                        yellow_gt=2,
                        red_gt=4,
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 12},
                    "id": 760440,
                },
                {
                    **_qv(
                        "Fil blindspots cegos",
                        "avg:robo.filamentos.ml.blindspot.cegos{*}",
                        aggregator="avg",
                        yellow_gt=2,
                        red_gt=4,
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 12},
                    "id": 760441,
                },
                {
                    **_qv(
                        "PETG rodadas monitor",
                        "sum:robo.masterprint_petg.rodadas{*}.as_count()",
                        aggregator="sum",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 12},
                    "id": 760442,
                },
                {
                    **_qv(
                        "Fil rodadas monitor",
                        "sum:robo.filamentos.ml.rodadas{*}.as_count()",
                        aggregator="sum",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 12},
                    "id": 760443,
                },
                {
                    **_qv(
                        "ML busca sites 403",
                        "sum:robo.ml.busca.sites_search_403{*}.as_count()",
                        aggregator="sum",
                        yellow_gt=0,
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 12},
                    "id": 760444,
                },
                {
                    **_qv(
                        "ML sem venda (itens)",
                        "avg:robo.ml.sem_venda.total{*}",
                        aggregator="avg",
                        yellow_gt=0,
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 12},
                    "id": 760445,
                },
                {
                    "id": 760450,
                    "definition": {
                        "title": "Acoes por tipo (Filamentos) — baixar_preco / titulo_ads / conversao",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "bars",
                                "response_format": "timeseries",
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": (
                                            "avg:robo.filamentos.ml.funil.acao."
                                            "baixar_preco_ou_listing{*}"
                                        ),
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": (
                                            "avg:robo.filamentos.ml.funil.acao."
                                            "melhorar_titulo_e_ads{*}"
                                        ),
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query3",
                                        "query": (
                                            "avg:robo.filamentos.ml.funil.acao."
                                            "melhorar_conversao_listing{*}"
                                        ),
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query4",
                                        "query": (
                                            "avg:robo.filamentos.ml.funil.acao."
                                            "republicar_ou_ads{*}"
                                        ),
                                    },
                                ],
                                "formulas": [
                                    {"alias": "baixar_preco", "formula": "query1"},
                                    {"alias": "titulo_ads", "formula": "query2"},
                                    {"alias": "conversao_listing", "formula": "query3"},
                                    {"alias": "republicar_ads", "formula": "query4"},
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 14},
                },
                {
                    "id": 760451,
                    "definition": {
                        "title": "Blindspots estruturais — cegos / parciais / oks",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.masterprint_petg.blindspot.cegos{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "avg:robo.filamentos.ml.blindspot.cegos{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query3",
                                        "query": "avg:robo.masterprint_petg.blindspot.parciais{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query4",
                                        "query": "avg:robo.filamentos.ml.blindspot.oks{*}",
                                    },
                                ],
                                "formulas": [
                                    {"alias": "petg_cegos", "formula": "query1"},
                                    {"alias": "fil_cegos", "formula": "query2"},
                                    {"alias": "petg_parciais", "formula": "query3"},
                                    {"alias": "fil_oks", "formula": "query4"},
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 14},
                },
            ],
        },
        "layout": {"x": 0, "y": 0, "width": 12, "height": 1},
    }


def _grupo_mercado_masterprint() -> dict[str, Any]:
    """Monitor ML — foco em anúncios, preço, margem e porte de seller (vendas API = n/d)."""
    return {
        "id": GROUP_MP_MERCADO_ID,
        "definition": {
            "title": "[Fase 2 · Mercado ML] Filamentos / PETG / Escritorio",
            "type": "group",
            "background_color": "vivid_purple",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    "id": 760200,
                    "definition": {
                        "type": "note",
                        "content": (
                            "**Vendas ML de concorrentes = indisponível (API 403).**\n"
                            "Use **anúncios / preço / margem / seller_transacoes**. "
                            "`seller_vendas_dia` só preenche se a API devolver `sold_quantity`. "
                            "Para **nossa conta** com Masterprint, o funil próprio "
                            "(`funil.unidades_7d` / visitas) é a leitura certa — "
                            "não o ranking de rivais."
                        ),
                        "background_color": "yellow",
                        "font_size": "14",
                        "text_align": "left",
                        "show_tick": False,
                        "has_padding": True,
                    },
                    "layout": {"height": 2, "width": 12, "x": 0, "y": 0},
                },
                {
                    **_qv(
                        "Filamentos unicos (ML)",
                        "avg:robo.filamentos.ml.total_unicos{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 2},
                    "id": 760201,
                },
                {
                    **_qv(
                        "Margem media PETG R$",
                        "avg:robo.masterprint_petg.margem_media_brl{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 2},
                    "id": 760202,
                },
                {
                    **_qv(
                        "Alibaba lucrativos",
                        "avg:robo.filamentos.ml.alibaba_lucrativos{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 2},
                    "id": 760203,
                },
                {
                    **_qv(
                        "PETG anuncios ML",
                        "avg:robo.masterprint_petg.anuncios{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 2},
                    "id": 760204,
                },
                {
                    **_qv(
                        "Sourcing COMPRAR_BR",
                        "avg:robo.filamentos.sourcing.comprar_br{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 4, "x": 0, "y": 4},
                    "id": 760210,
                },
                {
                    **_qv(
                        "Sourcing IMPORTAR_CHINA",
                        "avg:robo.filamentos.sourcing.importar_china{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 4, "x": 4, "y": 4},
                    "id": 760211,
                },
                {
                    **_qv(
                        "Sourcing NAO_COMPENSA",
                        "avg:robo.filamentos.sourcing.nao_compensa{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 4, "x": 8, "y": 4},
                    "id": 760212,
                },
                {
                    "id": 760220,
                    "definition": {
                        "title": "PETG — anuncios / preco / margem (vendas API n/d)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.masterprint_petg.anuncios{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "avg:robo.masterprint_petg.preco_medio{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query3",
                                        "query": "avg:robo.masterprint_petg.margem_media_brl{*}",
                                    },
                                ],
                                "formulas": [
                                    {"alias": "anuncios", "formula": "query1"},
                                    {"alias": "preco_medio", "formula": "query2"},
                                    {"alias": "margem_R$", "formula": "query3"},
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 6},
                },
                {
                    "id": 760221,
                    "definition": {
                        "title": "Escritorio — anuncios ativos (vendas API n/d)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.masterprint_escritorio.anuncios{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "avg:robo.masterprint_escritorio.rodadas{*}",
                                    },
                                ],
                                "formulas": [
                                    {"alias": "anuncios", "formula": "query1"},
                                    {"alias": "rodadas", "formula": "query2"},
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 6},
                },
                {
                    **_toplist_metric(
                        "Top anuncios PETG por margem (R$)",
                        "avg:robo.masterprint_petg.top_margem_rank{*} by {ad}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 0, "y": 9},
                    "id": 760230,
                },
                {
                    **_toplist_metric(
                        "Maiores sellers PETG (transacoes ML)",
                        "avg:robo.masterprint_petg.seller_transacoes{*} by {seller}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 4, "y": 9},
                    "id": 760231,
                },
                {
                    **_toplist_metric(
                        "Sellers PETG — anuncios ativos",
                        "avg:robo.masterprint_petg.seller_anuncios{*} by {seller}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 8, "y": 9},
                    "id": 760232,
                },
                {
                    **_toplist_metric(
                        "Top anuncios PETG por margem (detalhe)",
                        "avg:robo.masterprint_petg.top_margem{*} by {ad}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 0, "y": 12},
                    "id": 760233,
                },
                {
                    **_toplist_metric(
                        "Top anuncios PETG por preco",
                        "avg:robo.masterprint_petg.top_preco{*} by {ad}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 4, "y": 12},
                    "id": 760234,
                },
                {
                    **_toplist_metric(
                        "Maiores sellers Masterprint (mercado)",
                        "avg:robo.filamentos.ml.masterprint.seller_transacoes{*} by {seller}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 4, "x": 8, "y": 12},
                    "id": 760235,
                },
                {
                    **_toplist_metric(
                        "Sellers PETG — un/dia (se API vendas)",
                        "avg:robo.masterprint_petg.seller_vendas_dia{*} by {seller}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 15},
                    "id": 760236,
                },
                {
                    **_toplist_metric(
                        "Sellers Masterprint — un/dia (se API vendas)",
                        "avg:robo.filamentos.ml.masterprint.seller_vendas_dia{*} by {seller}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 15},
                    "id": 760237,
                },
            ],
        },
        "layout": {"x": 0, "y": 0, "width": 12, "height": 1},
    }


def _grupo_operacao_masterprint() -> dict[str, Any]:
    """Operação comercial — margem/preço/sellers (sem fingir vendas/receita zeradas)."""
    return {
        "id": GROUP_MP_COMERCIAL_ID,
        "definition": {
            "title": "[Fase 2 · Operacao comercial] Filamentos / Escritorio — margem e precificação",
            "type": "group",
            "background_color": "vivid_orange",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    "id": 760300,
                    "definition": {
                        "type": "note",
                        "content": (
                            "**Receita / lucro / vendas proxy = n/d** enquanto a API ML "
                            "bloquear `sold_quantity` de terceiros.\n"
                            "Decisão de preço: **margem média + preço médio + top margem + "
                            "porte do seller**."
                        ),
                        "background_color": "yellow",
                        "font_size": "14",
                        "text_align": "left",
                        "show_tick": False,
                        "has_padding": True,
                    },
                    "layout": {"height": 2, "width": 12, "x": 0, "y": 0},
                },
                {
                    **_qv(
                        "Margem media PETG R$",
                        "avg:robo.masterprint_petg.margem_media_brl{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 2},
                    "id": 760301,
                },
                {
                    **_qv(
                        "Preco medio PETG ML",
                        "avg:robo.masterprint_petg.preco_medio{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 2},
                    "id": 760302,
                },
                {
                    **_qv(
                        "PETG anuncios",
                        "avg:robo.masterprint_petg.anuncios{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 2},
                    "id": 760303,
                },
                {
                    **_qv(
                        "Seller txs (porte) PETG",
                        "avg:robo.masterprint_petg.seller_transacoes{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 2},
                    "id": 760304,
                },
                {
                    **_qv(
                        "Escritorio anuncios",
                        "avg:robo.masterprint_escritorio.anuncios{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 2},
                    "id": 760305,
                },
                {
                    **_qv(
                        "Custo medio tabela",
                        "avg:robo.masterprint.tabela.custo_medio{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 2},
                    "id": 760306,
                },
                {
                    "id": 760310,
                    "definition": {
                        "title": "PETG — preco medio vs margem media (R$)",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "line",
                                "response_format": "timeseries",
                                "formulas": [
                                    {"alias": "preco_medio", "formula": "query1"},
                                    {"alias": "margem_R$", "formula": "query2"},
                                ],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.masterprint_petg.preco_medio{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "avg:robo.masterprint_petg.margem_media_brl{*}",
                                    },
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 4},
                },
                {
                    "id": 760311,
                    "definition": {
                        "title": "Anuncios PETG vs Escritorio",
                        "type": "timeseries",
                        "show_legend": True,
                        "legend_layout": "horizontal",
                        "requests": [
                            {
                                "display_type": "bars",
                                "response_format": "timeseries",
                                "formulas": [
                                    {"alias": "petg", "formula": "query1"},
                                    {"alias": "escritorio", "formula": "query2"},
                                ],
                                "queries": [
                                    {
                                        "data_source": "metrics",
                                        "name": "query1",
                                        "query": "avg:robo.masterprint_petg.anuncios{*}",
                                    },
                                    {
                                        "data_source": "metrics",
                                        "name": "query2",
                                        "query": "avg:robo.masterprint_escritorio.anuncios{*}",
                                    },
                                ],
                            }
                        ],
                    },
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 4},
                },
                {
                    **_toplist_metric(
                        "Top anuncios por margem R$",
                        "avg:robo.masterprint_petg.top_margem{*} by {ad}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 7},
                    "id": 760320,
                },
                {
                    **_toplist_metric(
                        "Sellers por porte (transacoes)",
                        "avg:robo.masterprint_petg.seller_transacoes{*} by {seller}",
                        aggregator="avg",
                    ),
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 7},
                    "id": 760321,
                },
            ],
        },
        "layout": {"x": 0, "y": 0, "width": 12, "height": 1},
    }


def atualizar_dashboard_saude() -> None:
    """Dashboard Robo: saude do motor — sem Catalogo/Batalha (vao para Ecommerce)."""
    ecom_id = _resolver_dash_ecommerce()
    mp_id = _resolver_dash_masterprint()
    raw = _get(f"/api/v1/dashboard/{DASH_SAUDE}")
    widgets = list(raw.get("widgets") or [])
    novo: list[Any] = []
    substituido = False
    tokens_ok = False

    note = _note_widget(
        NOTE_ROBO_ID,
        (
            "## Aba Robo / plataforma\n\n"
            "Orquestrador, tokens, conectividade, vigia e falhas ops "
            "(chat / NF-e / estoque / telegram).\n\n"
            f"**Fase 1 Impala/ML:** [{DASH_ECOMMERCE_TITLE}]({_url_dash(ecom_id)})\n\n"
            f"**Fase 2 Masterprint:** "
            f"[{DASH_MASTERPRINT_TITLE}]({_url_dash(mp_id)})"
        ),
        background_color="blue",
        height=2,
    )

    for w in widgets:
        if not isinstance(w, dict):
            novo.append(w)
            continue
        if _eh_grupo_ecommerce(w) or _eh_note_navegacao(w):
            continue
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
        else:
            novo.append(w)

    novo.insert(0, note)
    if not substituido:
        novo.append(_grupo_pontos_cegos())
    if not tokens_ok:
        novo.insert(1, _grupo_tokens())

    payload = {
        "title": "Robo Marketplaces - Robo / Saude de Integracoes",
        "description": (
            "ABA ROBO: saude do motor (orquestrador, tokens, vigia, conectividade, "
            "pontos cegos ops). "
            f"ABA FASE 1 IMPALA: {_url_dash(ecom_id)} · "
            f"ABA FASE 2 MASTERPRINT: {_url_dash(mp_id)}"
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
    print(f"OK dashboard robo/saude: {_url_dash(DASH_SAUDE)}")


def _grupo_ponto_ruptura_cnae() -> dict[str, Any]:
    """Impala → 2º CNPJ: progresso da ruptura + gaps de CNAE/KYC Masterprint."""
    return {
        "id": GROUP_PONTO_RUPTURA_ID,
        "definition": {
            "title": "[CNAE / 2o CNPJ] Prepare agora · ruptura Impala depois",
            "type": "group",
            "background_color": "purple",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv(
                        "Gaps CNAE/KYC",
                        "avg:robo.cnae_preparacao.gaps{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 0},
                    "id": 770001,
                },
                {
                    **_qv(
                        "Seller Masterprint",
                        "avg:robo.cnae_preparacao.seller_masterprint{*}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 0},
                    "id": 770002,
                },
                {
                    **_qv(
                        "CNAE pronto (0/1)",
                        "avg:robo.cnae_preparacao.pronto{*}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 0},
                    "id": 770003,
                },
                {
                    **_qv(
                        "Aproximando Impala (0/1)",
                        "avg:robo.ponto_ruptura.aproximando{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 0},
                    "id": 770004,
                },
                {
                    **_qv(
                        "Liberado 2o CNPJ",
                        "avg:robo.ponto_ruptura.liberado{*}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 2},
                    "id": 770005,
                },
                {
                    **_qv(
                        "Progresso ruptura %",
                        "avg:robo.ponto_ruptura.progresso_pct{*}",
                        aggregator="avg",
                        green_gt=80,
                        yellow_gt=40,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 2},
                    "id": 770006,
                },
                {
                    **_qv(
                        "Avaliacoes Impala",
                        "avg:robo.ponto_ruptura.avaliacoes{*}",
                        aggregator="avg",
                        green_gt=19,
                        yellow_gt=9,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 2},
                    "id": 770007,
                },
                {
                    **_qv(
                        "Checks Impala ok",
                        "avg:robo.ponto_ruptura.checks_ok{*}",
                        aggregator="avg",
                        green_gt=6,
                        yellow_gt=3,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 2},
                    "id": 770008,
                },
                {
                    **_qv(
                        "Saude Impala (0-100)",
                        "avg:robo.ruptura.impala.saude_score{*}",
                        aggregator="avg",
                        green_gt=70,
                        yellow_lt=70,
                        red_lt=40,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 4},
                    "id": 770009,
                },
                {
                    **_qv(
                        "Kits margem segura",
                        "avg:robo.ruptura.impala.produtos_seguros{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 4},
                    "id": 770010,
                },
                {
                    **_qv(
                        "Margem media segura %",
                        "avg:robo.ruptura.impala.margem_media_segura_pct{*}",
                        aggregator="avg",
                        green_gt=14,
                        yellow_gt=9,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 4},
                    "id": 770011,
                },
                {
                    **_qv(
                        "Esforco faltando / Claude",
                        "avg:robo.ruptura.impala.esforco_faltando{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 4},
                    "id": 770012,
                },
                {
                    **_qv(
                        "Claude max pulso (0=moderado)",
                        "avg:robo.ruptura.impala.claude_assertividade_maxima{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 6},
                    "id": 770014,
                },
            ],
        },
        "layout": {"x": 0, "y": 8, "width": 12, "height": 1},
    }


def _grupo_saude_conta_ml() -> dict[str, Any]:
    """Reputação + anúncios + pós-venda da conta ML autenticada (não é radar de concorrente)."""
    return {
        "id": GROUP_SAUDE_CONTA_ML_ID,
        "definition": {
            "title": "[Saude conta ML] Reputacao / anuncios / pos-venda",
            "type": "group",
            "background_color": "vivid_green",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv(
                        "Vendas completadas",
                        "avg:robo.ml.saude.vendas_completadas{*}",
                        aggregator="avg",
                        green_gt=9,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 0},
                    "id": 780001,
                },
                {
                    **_qv(
                        "Avaliacoes",
                        "avg:robo.ml.saude.avaliacoes{*}",
                        aggregator="avg",
                        green_gt=19,
                        yellow_gt=9,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 0},
                    "id": 780002,
                },
                {
                    **_qv(
                        "Nota media",
                        "avg:robo.ml.saude.nota{*}",
                        aggregator="avg",
                        green_gt=4.7,
                        yellow_gt=4.0,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 0},
                    "id": 780003,
                },
                {
                    **_qv(
                        "Nivel reputacao (0-5)",
                        "avg:robo.ml.saude.nivel{*}",
                        aggregator="avg",
                        green_gt=4,
                        yellow_gt=2,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 0},
                    "id": 780004,
                },
                {
                    **_qv(
                        "Claims rate %",
                        "avg:robo.ml.saude.claims_rate_pct{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=1,
                        red_gt=2,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 0},
                    "id": 780005,
                },
                {
                    **_qv(
                        "Mercado Lider (0-3)",
                        "avg:robo.ml.saude.power_seller{*}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 0},
                    "id": 780006,
                },
                {
                    **_qv(
                        "Anuncios ativos",
                        "avg:robo.ml.saude.anuncios_ativos{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 2},
                    "id": 780007,
                },
                {
                    **_qv(
                        "Anuncios pausados",
                        "avg:robo.ml.saude.anuncios_pausados{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 2},
                    "id": 780008,
                },
                {
                    **_qv(
                        "Todos pausados (0/1)",
                        "avg:robo.ml.saude.todos_pausados{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 2},
                    "id": 780009,
                },
                {
                    **_qv(
                        "Anuncios a melhorar",
                        "avg:robo.ml.saude.anuncios_a_melhorar{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 2},
                    "id": 780010,
                },
                {
                    **_qv(
                        "Perguntas pendentes",
                        "avg:robo.ml.saude.perguntas_pendentes{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 2},
                    "id": 780011,
                },
                {
                    **_qv(
                        "Claims abertos",
                        "avg:robo.ml.saude.claims_abertos{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 2},
                    "id": 780012,
                },
                {
                    **_qv(
                        "Receita bruta R$ (pedidos)",
                        "avg:robo.vendas.receita_bruta{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 4},
                    "id": 780013,
                },
                {
                    **_qv(
                        "Lucro pedidos R$",
                        "avg:robo.vendas.lucro_reais{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 4},
                    "id": 780014,
                },
                {
                    **_qv(
                        "Margem pedidos %",
                        "avg:robo.vendas.margem_media_pct{*}",
                        aggregator="avg",
                        green_gt=10,
                        yellow_gt=0,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 4},
                    "id": 780015,
                },
                {
                    **_qv(
                        "P0 loja ativo (0/1)",
                        "avg:robo.ml.loja.p0.tem{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 4},
                    "id": 780016,
                },
                {
                    **_qv(
                        "Envios pendentes",
                        "avg:robo.ml.saude.envios_pendentes{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 4},
                    "id": 780017,
                },
                {
                    **_qv(
                        "Sem cor reputacao (0/1)",
                        "avg:robo.ml.saude.sem_cor{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 4},
                    "id": 780018,
                },
                {
                    **_qv(
                        "Bolsas/legado ignorados",
                        "avg:robo.ml.saude.anuncios_ignorados_fora_foco{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 6},
                    "id": 780019,
                },
                {
                    **_qv(
                        "Foco Impala vazio (0/1)",
                        "avg:robo.ml.saude.catalogo_foco_vazio{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 6},
                    "id": 780020,
                },
                {
                    **_qv(
                        "Integridade ML % (meta 99,99)",
                        "avg:robo.ml.integridade.pct{*}",
                        aggregator="avg",
                        red_lt=99.99,
                        green_gt=99.98,
                        precision=2,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 6},
                    "id": 780021,
                },
                {
                    **_qv(
                        "Telegram P0 enviado",
                        "sum:robo.ml.loja.p0.telegram_ok{*}.as_count()",
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 6},
                    "id": 780022,
                },
                {
                    **_qv(
                        "Telegram P0 skip",
                        "sum:robo.ml.loja.p0.telegram_skip{*}.as_count()",
                        green_gt=None,
                        yellow_gt=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 6},
                    "id": 780023,
                },
                {
                    **_qv(
                        "P0 chat falhas",
                        "avg:robo.ml.loja.p0.chat_falhas{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 6},
                    "id": 780024,
                },
                {
                    **_ts_overlay(
                        "P0 Telegram vs briefing 09:00",
                        [
                            ("P0 enviado", "sum:robo.ml.loja.p0.telegram_ok{*}.as_count()"),
                            ("P0 skip", "sum:robo.ml.loja.p0.telegram_skip{*}.as_count()"),
                            ("Briefing conta", "sum:robo.ml.resumo_conta.telegram_ok{*}.as_count()"),
                            ("P0 ativo", "avg:robo.ml.loja.p0.tem{*}"),
                        ],
                        palette="warm",
                    ),
                    "layout": {"height": 3, "width": 12, "x": 0, "y": 8},
                    "id": 780025,
                },
                {
                    **_qv(
                        "Ativos na conta (c/ legado)",
                        "avg:robo.ml.saude.anuncios_ativos_conta{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 11},
                    "id": 780026,
                },
                {
                    **_qv(
                        "Pausados na conta",
                        "avg:robo.ml.saude.anuncios_pausados_conta{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 11},
                    "id": 780027,
                },
                {
                    **_qv(
                        "Integridade IDs busca",
                        "avg:robo.ml.integridade.ids_busca{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 11},
                    "id": 780028,
                },
                {
                    **_qv(
                        "Integridade paging ML",
                        "avg:robo.ml.integridade.paging_total{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 11},
                    "id": 780029,
                },
                {
                    **_qv(
                        "Saude conta (cor/taxas, 0/1)",
                        "avg:robo.ml.saude.conta_ok{*}",
                        aggregator="last",
                        green_gt=0,
                        red_lt=1,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 13},
                    "id": 780030,
                },
                {
                    **_qv(
                        "Momento IG/FB no ciclo",
                        "avg:robo.meta.ciclo.pronto{*}",
                        aggregator="last",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 13},
                    "id": 780031,
                },
            ],
        },
        "layout": {"x": 0, "y": 8, "width": 12, "height": 1},
    }


def _grupo_ruptura_outra_marca() -> dict[str, Any]:
    """Mesmo CNPJ Impala: quando entrar com outra marca. Referente ML."""
    return {
        "id": GROUP_RUPTURA_OUTRA_MARCA_ID,
        "definition": {
            "title": "[Ruptura outra marca] CNPJ 52.668.583/0001-27 · referente ML",
            "type": "group",
            "background_color": "orange",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv(
                        "Liberado outra marca",
                        "avg:robo.marca_esmalte.ruptura.liberado{*}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 0},
                    "id": 790001,
                },
                {
                    **_qv(
                        "Aproximando outra marca (0/1)",
                        "avg:robo.marca_esmalte.ruptura.aproximando{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 0},
                    "id": 790002,
                },
                {
                    **_qv(
                        "Progresso %",
                        "avg:robo.marca_esmalte.ruptura.progresso_pct{*}",
                        aggregator="avg",
                        green_gt=80,
                        yellow_gt=40,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 0},
                    "id": 790003,
                },
                {
                    **_qv(
                        "Radar ML cego",
                        "avg:robo.marca_esmalte.ruptura.radar_cego{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 0},
                    "id": 790004,
                },
                {
                    **_qv(
                        "Checks outra marca ok",
                        "avg:robo.marca_esmalte.ruptura.checks_ok{*}",
                        aggregator="avg",
                        green_gt=5,
                        yellow_gt=2,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 2},
                    "id": 790005,
                },
                {
                    **_qv(
                        "Anuncios foco Impala",
                        "avg:robo.marca_esmalte.ruptura.anuncios_foco{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 2},
                    "id": 790006,
                },
                {
                    **_qv(
                        "CNPJ no ML",
                        "avg:robo.marca_esmalte.cnpj_canal{marketplace:mercadolivre}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 2},
                    "id": 790007,
                },
                {
                    **_qv(
                        "CNPJ na Shopee",
                        "avg:robo.marca_esmalte.cnpj_canal{marketplace:shopee}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 2},
                    "id": 790008,
                },
                {
                    **_qv(
                        "CNPJ no Magalu",
                        "avg:robo.marca_esmalte.cnpj_canal{marketplace:magalu}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 4},
                    "id": 790009,
                },
                {
                    **_qv(
                        "CNPJ na Amazon",
                        "avg:robo.marca_esmalte.cnpj_canal{marketplace:amazon}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 4},
                    "id": 790010,
                },
                {
                    **_qv(
                        "Top score (ML)",
                        "avg:robo.marca_esmalte.ruptura.top_score{*}",
                        aggregator="avg",
                        green_gt=20,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 4},
                    "id": 790011,
                },
                {
                    **_qv(
                        "Migracao fase (0=F0)",
                        "avg:robo.migracao.fase{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 4},
                    "id": 790013,
                },
                {
                    **_qv(
                        "Migracao bloqueada (0/1)",
                        "avg:robo.migracao.bloqueada{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 6},
                    "id": 790014,
                },
                {
                    **_qv(
                        "Migracao Impala liberado",
                        "avg:robo.migracao.impala_liberado{*}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 6},
                    "id": 790015,
                },
                {
                    **_qv(
                        "Migracao saude conta",
                        "avg:robo.migracao.saude_conta{*}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 6},
                    "id": 790016,
                },
                {
                    **_qv(
                        "CNPJ2 pode operar",
                        "avg:robo.migracao.cnpj2_pode_operar{*}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 6},
                    "id": 790017,
                },
                {
                    **_toplist_metric(
                        "Marcas candidatas (score ML, sem Impala)",
                        "avg:robo.marca_esmalte.candidata.score{*} by {marca}",
                        aggregator="avg",
                        limit=10,
                    ),
                    "layout": {"height": 4, "width": 12, "x": 0, "y": 8},
                    "id": 790012,
                },
            ],
        },
        "layout": {"x": 0, "y": 12, "width": 12, "height": 1},
    }


def _grupo_marca_kit_tendencia() -> dict[str, Any]:
    """Marcas e tamanhos de kit no ML cruzados com tendência."""
    return {
        "id": GROUP_MARCA_KIT_TENDENCIA_ID,
        "definition": {
            "title": "[Marca x kit x tendencia] Condicao no ML + desempenho",
            "type": "group",
            "background_color": "vivid_orange",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv(
                        "Combos marca/kit",
                        "avg:robo.esmaltes.marca_kit.total{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 0},
                    "id": 791001,
                },
                {
                    **_qv(
                        "Boa performance (tendencia)",
                        "avg:robo.esmaltes.marca_kit.boas_performance{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 0},
                    "id": 791002,
                },
                {
                    **_toplist_metric(
                        "Score por marca (ML x tendencia)",
                        "avg:robo.esmaltes.marca_kit.score{*} by {marca}",
                        aggregator="avg",
                        limit=10,
                    ),
                    "layout": {"height": 4, "width": 6, "x": 6, "y": 0},
                    "id": 791003,
                },
                {
                    **_toplist_metric(
                        "Score por tamanho de kit",
                        "avg:robo.esmaltes.marca_kit.score{*} by {kit}",
                        aggregator="avg",
                        limit=8,
                    ),
                    "layout": {"height": 4, "width": 6, "x": 0, "y": 2},
                    "id": 791004,
                },
            ],
        },
        "layout": {"x": 0, "y": 14, "width": 12, "height": 1},
    }


def _grupo_kits_manicure_impala() -> dict[str, Any]:
    """Kits Impala para manicure: condição, economia vs avulso, índice de compra."""
    return {
        "id": GROUP_KITS_MANICURE_ID,
        "definition": {
            "title": "[Kits Impala manicure] Condicao + economia + indice de compra",
            "type": "group",
            "background_color": "vivid_blue",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv(
                        "Kits avaliados",
                        "avg:robo.esmaltes.kit_manicure.total{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 0},
                    "id": 791011,
                },
                {
                    **_qv(
                        "Com condicao (economia ou MIMO extra)",
                        "avg:robo.esmaltes.kit_manicure.condicao_ok{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 0},
                    "id": 791012,
                },
                {
                    **_qv(
                        "Economia media vs avulso %",
                        "avg:robo.esmaltes.kit_manicure.economia_media_pct{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 0},
                    "id": 791013,
                },
                {
                    **_toplist_metric(
                        "Indice de compra Impala por kit",
                        "avg:robo.esmaltes.kit_manicure.indice_compra{*} by {kit}",
                        aggregator="avg",
                        limit=10,
                    ),
                    "layout": {"height": 4, "width": 6, "x": 0, "y": 2},
                    "id": 791014,
                },
                {
                    **_toplist_metric(
                        "Economia % vs avulso por kit",
                        "avg:robo.esmaltes.kit_manicure.economia_pct{*} by {kit}",
                        aggregator="avg",
                        limit=8,
                    ),
                    "layout": {"height": 4, "width": 6, "x": 6, "y": 2},
                    "id": 791015,
                },
            ],
        },
        "layout": {"x": 0, "y": 16, "width": 12, "height": 1},
    }


def _grupo_decisao_oscilacao() -> dict[str, Any]:
    """Qualquer oscilação além da margem âncora → vermelho + cuidado para decidir."""
    return {
        "id": GROUP_DECISAO_OSCILACAO_ID,
        "definition": {
            "title": "[Decisao] Oscilacao Datadog · cuidado · Claude moderado",
            "type": "group",
            "background_color": "vivid_red",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    **_qv(
                        "OSCILACAO (0/1) — widget vermelho",
                        "avg:robo.decisao.oscilacao{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 0, "y": 0},
                    "id": 791021,
                },
                {
                    **_qv(
                        "CUIDADO para decidir (0/1)",
                        "avg:robo.decisao.cuidado{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 2, "y": 0},
                    "id": 791022,
                },
                {
                    **_qv(
                        "Metricas que oscilaram",
                        "avg:robo.decisao.oscilacao.n{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 4, "y": 0},
                    "id": 791023,
                },
                {
                    **_qv(
                        "Claude pulso maximo (0=moderado)",
                        "avg:robo.claude.ciclo.fase_maxima{*}",
                        aggregator="avg",
                        green_gt=None,
                        yellow_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 6, "y": 0},
                    "id": 791024,
                },
                {
                    **_qv(
                        "Dados expostos no Datadog",
                        "avg:robo.claude.ciclo.exposto_datadog{*}",
                        aggregator="avg",
                        green_gt=0.5,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 8, "y": 0},
                    "id": 791025,
                },
                {
                    **_qv(
                        "Vigia Datadog saudavel",
                        "avg:robo.vigia_datadog.saudavel{*}",
                        aggregator="avg",
                        green_gt=0.5,
                        red_lt=1,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 2, "x": 10, "y": 0},
                    "id": 791026,
                },
            ],
        },
        "layout": {"x": 0, "y": 18, "width": 12, "height": 1},
    }


def _grupo_progresso_24m() -> dict[str, Any]:
    """Fase 1 Impala: lucro/mês vs 2.5k/20k e Cruzeiro 12/dia. Sem Masterprint/PETG."""
    ts_impala = _ts_overlay(
        "Lucro/mes Impala vs metas (fase 1)",
        [
            ("Impala", "avg:robo.progresso.lucro_mes_impala{*}"),
            ("meta ano 1 R$ 2.5k", "avg:robo.progresso.meta_lucro_ano1_mes{*}"),
            ("meta alvo R$ 20k", "avg:robo.progresso.meta_lucro_alvo_mes{*}"),
        ],
        palette="cool",
    )
    ts_ritmo = _ts_overlay(
        "Ritmo/dia — Cruzeiro vs 12 (fase 1)",
        [
            ("Cruzeiro unid/dia", "avg:robo.progresso.cruzeiro_unid_dia{*}"),
            ("meta Cruzeiro 12", "avg:robo.progresso.meta_cruzeiro_unid_dia{*}"),
        ],
        palette="warm",
    )
    pct_ano1 = _qv_formula(
        "% da meta ano 1 (Impala)",
        [
            ("query1", "avg:robo.progresso.lucro_mes_impala{*}"),
            ("query2", "avg:robo.progresso.meta_lucro_ano1_mes{*}"),
        ],
        "query1 / query2 * 100",
        aggregator="avg",
        green_gt=80,
        yellow_gt=10,
        red_lt=5,
        precision=0,
    )
    return {
        "id": GROUP_PROGRESSO_24M_ID,
        "definition": {
            "title": "[Fase 1 / Impala] Progresso 24 meses",
            "type": "group",
            "background_color": "vivid_orange",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    "id": 781000,
                    "definition": {
                        "type": "note",
                        "content": (
                            "**Fase 1 = Impala (esmaltes / Cruzeiro).** Sem misturar "
                            "filamento Masterprint. Relogio comeca quando MIMO vender. "
                            "Lucro/mes Impala = (lucro SKU IMP/CRZ/BUNDLE na janela ÷ dias) × 30. "
                            "PETG, lucro Masterprint e funil de filamento ficam na "
                            "**aba Fase 2**. Reviews 20 e ruptura % ficam no grupo "
                            "[CNAE / 2o CNPJ]. 0 e o estado correto ate o 1o pedido."
                        ),
                        "background_color": "orange",
                        "font_size": "14",
                        "text_align": "left",
                        "show_tick": False,
                        "has_padding": True,
                    },
                    "layout": {"height": 2, "width": 12, "x": 0, "y": 0},
                },
                {
                    **_qv(
                        "Lucro/mes Impala R$",
                        "avg:robo.progresso.lucro_mes_impala{*}",
                        aggregator="avg",
                        green_gt=2500,
                        yellow_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 2},
                    "id": 781003,
                },
                {
                    **pct_ano1,
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 2},
                    "id": 781002,
                },
                {
                    **_qv(
                        "Cruzeiro unid/dia",
                        "avg:robo.progresso.cruzeiro_unid_dia{*}",
                        aggregator="avg",
                        green_gt=11,
                        yellow_gt=0,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 2},
                    "id": 781005,
                },
                {
                    **_qv(
                        "Meta Cruzeiro 12/dia",
                        "avg:robo.progresso.meta_cruzeiro_unid_dia{*}",
                        aggregator="avg",
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 2},
                    "id": 781007,
                },
                {
                    **ts_impala,
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 4},
                    "id": 781020,
                },
                {
                    **ts_ritmo,
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 4},
                    "id": 781021,
                },
            ],
        },
        "layout": {"x": 0, "y": 1, "width": 12, "height": 1},
    }


def _grupo_progresso_fase2_masterprint() -> dict[str, Any]:
    """Fase 2 Masterprint: lucro filamento/escritorio e ritmo PETG 6/dia."""
    ts_mp = _ts_overlay(
        "Lucro/mes Masterprint vs metas (fase 2)",
        [
            ("Masterprint", "avg:robo.progresso.lucro_mes_masterprint{*}"),
            ("meta ano 1 R$ 2.5k", "avg:robo.progresso.meta_lucro_ano1_mes{*}"),
            ("meta alvo R$ 20k", "avg:robo.progresso.meta_lucro_alvo_mes{*}"),
        ],
        palette="cool",
    )
    ts_petg = _ts_overlay(
        "Ritmo/dia — PETG vs 6 (fase 2)",
        [
            ("PETG unid/dia", "avg:robo.progresso.petg_unid_dia{*}"),
            ("meta PETG 6", "avg:robo.progresso.meta_petg_unid_dia{*}"),
        ],
        palette="cool",
    )
    pct_petg = _qv_formula(
        "% da meta PETG 6/dia",
        [
            ("query1", "avg:robo.progresso.petg_unid_dia{*}"),
            ("query2", "avg:robo.progresso.meta_petg_unid_dia{*}"),
        ],
        "query1 / query2 * 100",
        aggregator="avg",
        green_gt=80,
        yellow_gt=10,
        red_lt=5,
        precision=0,
    )
    return {
        "id": GROUP_PROGRESSO_FASE2_ID,
        "definition": {
            "title": "[Fase 2 / Masterprint] Progresso PETG / filamentos",
            "type": "group",
            "background_color": "vivid_purple",
            "layout_type": "ordered",
            "show_title": True,
            "widgets": [
                {
                    "id": 781100,
                    "definition": {
                        "type": "note",
                        "content": (
                            "**Fase 2 = Masterprint (filamentos / escritorio / 2o CNPJ).** "
                            "Nao misturar com Impala. Lucro/mes = SKUs que nao sao "
                            "IMP/CRZ/BUNDLE. Ritmo operacional = PETG unid/dia vs 6. "
                            "Operar so depois da ruptura Impala (checklist na aba Fase 1). "
                            "0 e o estado correto ate o 1o pedido PETG."
                        ),
                        "background_color": "purple",
                        "font_size": "14",
                        "text_align": "left",
                        "show_tick": False,
                        "has_padding": True,
                    },
                    "layout": {"height": 2, "width": 12, "x": 0, "y": 0},
                },
                {
                    **_qv(
                        "Lucro/mes Masterprint R$",
                        "avg:robo.progresso.lucro_mes_masterprint{*}",
                        aggregator="avg",
                        green_gt=0,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 0, "y": 2},
                    "id": 781004,
                },
                {
                    **_qv(
                        "PETG unid/dia",
                        "avg:robo.progresso.petg_unid_dia{*}",
                        aggregator="avg",
                        green_gt=5,
                        yellow_gt=0,
                        precision=1,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 3, "y": 2},
                    "id": 781006,
                },
                {
                    **pct_petg,
                    "layout": {"height": 2, "width": 3, "x": 6, "y": 2},
                    "id": 781108,
                },
                {
                    **_qv(
                        "Meta PETG 6/dia",
                        "avg:robo.progresso.meta_petg_unid_dia{*}",
                        aggregator="avg",
                        green_gt=None,
                        precision=0,
                    ),
                    "layout": {"height": 2, "width": 3, "x": 9, "y": 2},
                    "id": 781109,
                },
                {
                    **ts_mp,
                    "layout": {"height": 3, "width": 6, "x": 0, "y": 4},
                    "id": 781120,
                },
                {
                    **ts_petg,
                    "layout": {"height": 3, "width": 6, "x": 6, "y": 4},
                    "id": 781121,
                },
            ],
        },
        "layout": {"x": 0, "y": 1, "width": 12, "height": 1},
    }


def atualizar_dashboard_ecommerce() -> None:
    """Dashboard Ecommerce: catalogo, batalha, ads/vendas/decisao."""
    ecom_id = _resolver_dash_ecommerce()
    mp_id = _resolver_dash_masterprint()
    raw = _get(f"/api/v1/dashboard/{ecom_id}")

    note = _note_widget(
        NOTE_ECOM_ID,
        (
            "## Aba Fase 1 — Impala / ML\n\n"
            "Leitura: **receita / lucro / margem** + **produto (kit) com preco/custo/lucro**, "
            "**invest. validacao**, **kits Cruzeiro**, **oportunidades/Livia**, "
            "**taxa de crescimento** e **custo/Ads**.\n\n"
            "**Progresso fase 1:** grupo [Fase 1 / Impala] — só lucro Impala "
            "(SKU IMP/CRZ/BUNDLE) vs R$ 2.5k / R$ 20k e Cruzeiro unid/dia vs 12. "
            "PETG e lucro Masterprint **não entram aqui** — estão na aba Fase 2. "
            "Teto, não previsão; 0 até o 1º pedido MIMO.\n\n"
            "**2o CNPJ / CNAE:** grupo [CNAE / 2o CNPJ] — gaps de KYC agora; "
            "liberado só quando Impala bater a checklist (20 reviews / 4.8 / MLB / estoque).\n\n"
            "**Outra marca de esmalte:** grupo [Ruptura outra marca] — mesmo CNPJ "
            "52.668.583/0001-27 em todos os canais; Mercado Livre é o referente de "
            "demanda (Anita / Risque / Colorama / …). Liberado só com checklist Impala "
            "+ anúncio ativo + radar ML com amostra. Claude entra no veredito "
            "aproximando/liberado com esforço, produtos de margem segura e prévia ML.\n\n"
            "**Marca × kit × tendência:** grupo [Marca x kit x tendencia] — o robô "
            "identifica no ML marcas e tamanhos de kit que oferecem condição e cruzam "
            "com tendência (confirmada/oportunidade).\n\n"
            "**Kits manicure Impala:** grupo [Kits Impala manicure] — kits do catálogo "
            "compatíveis com o que o ML oferece, com índice de compra Impala, economia "
            "vs avulso e condição (qtd≥3 + margem ≥ piso + padrão Impala). "
            "MIMO entra por extra Carmed (economia vs avulso pode ser negativa).\n\n"
            "**Decisão guerra Impala:** grupo [Decisao guerra Impala] — fase 0–5 "
            "(0=abrir MIMO, não é erro), publicar_agora (gate, não os 20 kits), "
            "título de atração (Impala+esmalte+Carmed+manicure), Carmed no ar, "
            "MIMO como entrada da manicure (não economia vs avulso), "
            "canal_liberado por marketplace (ML referente; Shopee/Magalu/Amazon só fase 3+), "
            "margem/lucro do catálogo + Cruzeiro spa + pipeline onda 2. "
            "Rivais comparáveis só com amostra viva. Telegram aponta "
            "para este grupo. Cache STALE não entra como mercado. "
            "IG/FB entra no ciclo só com `meta.ciclo.pronto=1` (saúde conta ML "
            "sem laranja/vermelho + Impala fase 3 Ads: 20 reviews / nota 4.8 / frente no ar); "
            "campanhas IG/FB ficam 0 até existirem na Meta. "
            "Eficiência Ads×ML no mesmo grupo: ROAS real (receita ML / gasto Meta), "
            "conversão impressão→pedido e clique→pedido, CPA, cobertura e status "
            "(não atribui pedido a IG vs FB — sem UTM).\n\n"
            "**Decisão / oscilação:** grupo [Decisao] — Claude pulsa assertividade "
            "máxima só para expor âncoras no Datadog e volta a uso moderado. "
            "Qualquer oscilação além da margem de erro deixa o widget **vermelho** "
            "e dispara Telegram: cuidado para tomar decisão (não escalar Ads/volume).\n\n"
            "**Saude da conta ML:** grupo [Saude conta ML] — reputação/cor da *conta*, "
            "anúncios do foco Impala (kits), claims e receita dos *seus* pedidos. "
            "Bolsas Mariart/legado ficam fora do radar "
            "(widgets Bolsas/legado ignorados e Foco Impala vazio). "
            "P0 loja (envio/pergunta/cor) vai ao Telegram no ciclo 30 min; "
            "widgets P0 ativo / Telegram P0 vs briefing 09:00.\n\n"
            "**Migracao de marcas:** gauges `robo.migracao.*` no grupo "
            "[Ruptura outra marca] (fase F0/F1, bloqueada, Impala liberado, CNPJ2).\n\n"
            f"**Robo / plataforma:** [Robo Marketplaces - Robo / Saude]({_url_dash(DASH_SAUDE)})\n\n"
            f"**Fase 2 Masterprint (filamentos / pinceis / apagadores):** "
            f"[{DASH_MASTERPRINT_TITLE}]({_url_dash(mp_id)})"
        ),
        background_color="orange",
        height=5,
    )
    prog = _grupo_progresso_24m()
    prog["layout"] = {"x": 0, "y": 1, "width": 12, "height": 1}
    cat = _grupo_catalogo_impala()
    cat["layout"] = {"x": 0, "y": 2, "width": 12, "height": 1}
    bat = _grupo_batalha_impala()
    bat["layout"] = {"x": 0, "y": 4, "width": 12, "height": 1}
    guerra = _grupo_decisao_guerra_impala()
    guerra["layout"] = {"x": 0, "y": 5, "width": 12, "height": 1}
    com = _grupo_operacao_comercial()
    com["layout"] = {"x": 0, "y": 6, "width": 12, "height": 1}
    saude = _grupo_saude_conta_ml()
    saude["layout"] = {"x": 0, "y": 8, "width": 12, "height": 1}
    ruptura = _grupo_ponto_ruptura_cnae()
    ruptura["layout"] = {"x": 0, "y": 10, "width": 12, "height": 1}
    outra = _grupo_ruptura_outra_marca()
    outra["layout"] = {"x": 0, "y": 12, "width": 12, "height": 1}
    marca_kit = _grupo_marca_kit_tendencia()
    marca_kit["layout"] = {"x": 0, "y": 14, "width": 12, "height": 1}
    kits_m = _grupo_kits_manicure_impala()
    kits_m["layout"] = {"x": 0, "y": 16, "width": 12, "height": 1}
    decisao = _grupo_decisao_oscilacao()
    decisao["layout"] = {"x": 0, "y": 18, "width": 12, "height": 1}

    payload = {
        "title": DASH_ECOMMERCE_TITLE,
        "description": (
            "ABA FASE 1 IMPALA: progresso Impala (teto 2.5k→20k, Cruzeiro 12/d; sem PETG/Masterprint), "
            "catalogo Impala, batalha, decisao guerra (margem+extra), ads, saude da conta ML, "
            "CNAE/2o CNPJ, ruptura outra marca, marca x kit x tendencia, "
            "kits Impala manicure, oscilacao/cuidado para decidir. "
            f"ABA ROBO: {_url_dash(DASH_SAUDE)} · "
            f"ABA FASE 2 MASTERPRINT: {_url_dash(mp_id)}"
        ),
        "widgets": [
            note,
            prog,
            com,
            cat,
            bat,
            guerra,
            saude,
            ruptura,
            outra,
            marca_kit,
            kits_m,
            decisao,
        ],
        "layout_type": raw.get("layout_type") or "ordered",
        "template_variables": raw.get("template_variables") or [],
        "notify_list": raw.get("notify_list") or [],
        "reflow_type": raw.get("reflow_type"),
        "tags": list({*(raw.get("tags") or []), "team:robo-markplaces"}),
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    _put(f"/api/v1/dashboard/{ecom_id}", payload)
    print(f"OK dashboard ecommerce: {_url_dash(ecom_id)}")


def atualizar_dashboard_masterprint() -> None:
    """Dashboard Fase 2 Masterprint: progresso PETG + catalogo / mercado / comercial."""
    mp_id = _resolver_dash_masterprint()
    ecom_id = _resolver_dash_ecommerce()
    raw = _get(f"/api/v1/dashboard/{mp_id}")

    note = _note_widget(
        NOTE_MP_ID,
        (
            "## Aba Fase 2 — Masterprint Filamentos / Escritorio\n\n"
            "Tudo desta aba é **Masterprint (2o CNPJ)**. Impala (esmaltes / Cruzeiro) "
            "fica só na aba Fase 1.\n\n"
            "Leitura: **progresso PETG** → **funil próprio** → **custo/catalogo** → "
            "**mercado ML** → **margem / preço / sellers**.\n\n"
            "**Progresso fase 2:** grupo [Fase 2 / Masterprint] — lucro Masterprint "
            "(SKU que não é IMP/CRZ/BUNDLE) e PETG unid/dia vs 6.\n"
            "**Funil:** visitas→unidades→conversão% + ações críticas "
            "(otimizador prioriza IDs).\n"
            "**Atenção:** vendas/receita/lucro de concorrentes ficam **n/d** (API ML 403). "
            "Use visitas rivais como proxy de demanda.\n\n"
            "**CNAE / ruptura Impala:** gate na aba Fase 1 (não copie métricas Impala aqui). "
            "Operar filamento no ar só depois da checklist Impala.\n\n"
            f"**Robo / plataforma:** [Robo / Saude]({_url_dash(DASH_SAUDE)})\n\n"
            f"**Fase 1 Impala:** [{DASH_ECOMMERCE_TITLE}]({_url_dash(ecom_id)})"
        ),
        background_color="purple",
        height=4,
    )
    prog = _grupo_progresso_fase2_masterprint()
    prog["layout"] = {"x": 0, "y": 2, "width": 12, "height": 1}
    funil = _grupo_funil_demanda_masterprint()
    funil["layout"] = {"x": 0, "y": 4, "width": 12, "height": 1}
    cat = _grupo_catalogo_masterprint()
    cat["layout"] = {"x": 0, "y": 6, "width": 12, "height": 1}
    merc = _grupo_mercado_masterprint()
    merc["layout"] = {"x": 0, "y": 8, "width": 12, "height": 1}
    com = _grupo_operacao_masterprint()
    com["layout"] = {"x": 0, "y": 10, "width": 12, "height": 1}

    payload = {
        "title": DASH_MASTERPRINT_TITLE,
        "description": (
            "ABA FASE 2 MASTERPRINT: progresso PETG/filamento, funil visitas→vendas, "
            "catalogo e mercado ML. Sem métricas Impala. "
            f"ABA ROBO: {_url_dash(DASH_SAUDE)} · ABA FASE 1 IMPALA: {_url_dash(ecom_id)}"
        ),
        "widgets": [note, prog, funil, com, cat, merc],
        "layout_type": raw.get("layout_type") or "ordered",
        "template_variables": raw.get("template_variables") or [],
        "notify_list": raw.get("notify_list") or [],
        "reflow_type": raw.get("reflow_type"),
        "tags": list({*(raw.get("tags") or []), "team:robo-markplaces"}),
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    _put(f"/api/v1/dashboard/{mp_id}", payload)
    print(f"OK dashboard masterprint: {_url_dash(mp_id)}")


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
    ecom_id = DASH_ECOMMERCE or _resolver_dash_ecommerce()
    msg_base = (
        "{{#is_alert}}Robo Marketplaces em alerta.{{/is_alert}}\n"
        "{{#is_recovery}}Recuperado.{{/is_recovery}}\n"
        f"Dashboard Robo: {_url_dash(DASH_SAUDE)}\n"
        f"Dashboard Ecommerce: {_url_dash(ecom_id)}\n"
        "Tags: service:robo-markplaces"
    )
    msg_ecom = (
        "{{#is_alert}}Robo Marketplaces em alerta.{{/is_alert}}\n"
        "{{#is_recovery}}Recuperado.{{/is_recovery}}\n"
        f"Dashboard Ecommerce: {_url_dash(ecom_id)}\n"
        f"Dashboard Robo: {_url_dash(DASH_SAUDE)}\n"
        "Tags: service:robo-markplaces"
    )
    return [
        {
            "name": "[Masterprint] Funil ML — acoes criticas",
            "type": "query alert",
            "query": (
                "avg(last_4h):(avg:robo.masterprint_petg.funil.acoes_criticas{*} + "
                "avg:robo.filamentos.ml.funil.acoes_criticas{*}) > 0"
            ),
            "message": (
                "Funil proprio com acoes criticas "
                "(visitas sem conversao / conversao baixa). "
                "Veja grupo [Fase 2 · Funil ML] no dashboard Fase 2 Masterprint e "
                "logs/funil_ml_acoes_ultima.json.\n"
                f"Dashboard: {_url_dash(DASH_MASTERPRINT)}\n" + msg_base
            ),
            "tags": [TAG_MONITOR, "monitor:funil_ml", "severity:p3"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 3,
        },
        {
            "name": "[Robo] Orquestrador sem ciclos (2h)",
            "type": "query alert",
            "query": "avg(last_2h):avg:robo.orquestrador.ciclo.pulse{*} < 1",
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
                'logs("service:robo-markplaces (Magalu OR \\"Magazine Luiza\\") '
                '(401 OR 400 OR invalid_grant)")'
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
                "veja '[Robo] Product Ads indisponivel'.\n" + msg_ecom
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
            "query": "avg(last_2h):avg:robo.ads.indisponivel_agora{*} > 0.5",
            "message": (
                "Product Ads ML retornou HTTP 404 (escopo advertising / advertiser). "
                "Corrija no DevCenter e regenere o token. "
                "Gatilho NAO pede aprovacao Telegram enquanto isto persistir.\n" + msg_ecom
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
            "name": "[Robo] Integridade dados ML abaixo de 99,99%",
            "type": "query alert",
            "query": "avg(last_1h):avg:robo.ml.integridade.pct{*} < 99.99",
            "message": (
                "Espelho ML abaixo de 99,99% vs API ao vivo. "
                "Listagem incompleta, GET /items falhou ou IDs faltando. "
                "Nao tome preco/estoque como verdade ate o widget voltar ao verde.\n"
                + msg_ecom
            ),
            "tags": [TAG_MONITOR, "monitor:integridade_ml", "severity:p2"],
            "options": {
                "thresholds": {"critical": 99.99},
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
                "monitor Magalu).\n" + msg_ecom
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
                "Separado do P1 de busca generica.\n" + msg_ecom
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
                "Publique MIMO-003 / PERL-004 / JU PAES-006 antes de ads/promocao.\n" + msg_ecom
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
                "Revise preco F1 / Full / taxa vs custo_total.\n" + msg_ecom
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
        {
            "name": "[Robo] CNAE segundo CNPJ — prepare (gaps)",
            "type": "query alert",
            "query": "avg(last_2d):avg:robo.cnae_preparacao.gaps{*} > 0",
            "message": (
                "Ainda falta preparar o 2o CNPJ (Masterprint 23.811.261/0001-97) "
                "antes da ruptura do Impala.\n"
                "Gaps tipicos: seller_id ML vazio (KYC) ou CNAE 4751-2/01 / "
                "4689-3/02 / 4761-0/03 ausente.\n"
                "Acao: Junta/Receita + KYC ML; preencher MASTERPRINT_ML_SELLER_ID. "
                "Nao publique o catalogo nem ligue CNPJ_DONO_PRODUTOS_USAR_ALVO.\n"
                "Telegram semanal: agente ponto_ruptura_segundo_cnpj (08:05 BRT).\n"
                + msg_ecom
            ),
            "tags": [TAG_MONITOR, "monitor:cnae_prep", "severity:p3"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 3,
        },
        {
            "name": "[Robo] Ponto ruptura — Impala aproximando",
            "type": "query alert",
            "query": "avg(last_2d):avg:robo.ponto_ruptura.aproximando{*} > 0.5",
            "message": (
                "Impala esta se aproximando do ponto de ruptura (reviews/estoque/MLB). "
                "Claude + briefing: esforco restante, kits com margem segura e previa do ML. "
                "Nao escale Ads nem outra marca ate a checklist fechar. "
                "Nao ligue o 2o CNPJ nem CNPJ_DONO_PRODUTOS_USAR_ALVO.\n"
                + msg_ecom
            ),
            "tags": [TAG_MONITOR, "monitor:ponto_ruptura", "severity:p2"],
            "options": {
                "thresholds": {"critical": 0.5},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Ponto ruptura — segundo CNPJ liberado",
            "type": "query alert",
            "query": "avg(last_2d):avg:robo.ponto_ruptura.liberado{*} > 0.5",
            "message": (
                "Checklist Impala completa (20 reviews / 4.8 / MLB kits / estoque / "
                "pedido / ACOS). Segundo CNPJ pode entrar em acao: 1 filamento "
                "PLA/PETG preto, Bling + token ML deste CNPJ, chat separado. "
                "Ads Masterprint so depois. Nao ligue CNPJ_DONO_PRODUTOS_USAR_ALVO ainda.\n"
                + msg_ecom
            ),
            "tags": [TAG_MONITOR, "monitor:ponto_ruptura", "severity:p2"],
            "options": {
                "thresholds": {"critical": 0.5},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Ponto ruptura — outra marca de esmalte liberada",
            "type": "query alert",
            "query": "avg(last_2d):avg:robo.marca_esmalte.ruptura.liberado{*} > 0.5",
            "message": (
                "Checklist Impala + anuncio ativo + radar ML com amostra. "
                "CNPJ 52.668.583/0001-27 pode entrar com a top marca do ranking ML "
                "(Anita/Risque/Colorama/…). Comecar no Mercado Livre; "
                "Shopee/Magalu/Amazon usam o mesmo CNPJ quando o canal ligar.\n"
                "Nao e o 2o CNPJ Masterprint.\n"
                + msg_ecom
            ),
            "tags": [TAG_MONITOR, "monitor:marca_esmalte", "severity:p2"],
            "options": {
                "thresholds": {"critical": 0.5},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 2,
        },
        {
            "name": "[Robo] Oscilacao Datadog — cuidado para decidir",
            "type": "query alert",
            "query": "avg(last_15m):avg:robo.decisao.oscilacao{*} > 0",
            "message": (
                "Widget vermelho: metrica de decisao oscilou alem da margem de erro "
                "(saude ±2, margem ±0,5 p.p., kits/Claude/anuncios). "
                "CUIDADO para tomar decisao — nao escale Ads, volume nem 2o CNPJ "
                "ate o widget sair do vermelho. Telegram tambem alerta.\n"
                + msg_ecom
            ),
            "tags": [TAG_MONITOR, "monitor:oscilacao_decisao", "severity:p2"],
            "options": {
                "thresholds": {"critical": 0},
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
    # Resolve dashboards primeiro para notes/links cruzados.
    ecom_id = _resolver_dash_ecommerce()
    mp_id = _resolver_dash_masterprint()
    atualizar_dashboard_ecommerce()
    atualizar_dashboard_masterprint()
    atualizar_dashboard_saude()
    _strip_cpu_ops_dashboard()
    upsert_monitores()
    print(f"Aba Robo:         {_url_dash(DASH_SAUDE)}")
    print(f"Aba Fase 1 Impala:{_url_dash(ecom_id)}")
    print(f"Aba Fase 2 MP:    {_url_dash(mp_id)}")
    print("Monitores: https://us5.datadoghq.com/monitors/manage?q=tag%3Aservice%3Arobo-markplaces")
    print("Nota: OAuth Magalu continua manual (token invalid_grant nos logs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
