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
TAG_MONITOR = "service:robo-markplaces"


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
                        "Meta Campanhas Critico",
                        "avg:robo.meta.campanhas_critico{*}",
                        aggregator="avg",
                        green_gt=None,
                        red_gt=0,
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


def atualizar_dashboard_saude() -> None:
    raw = _get(f"/api/v1/dashboard/{DASH_SAUDE}")
    widgets = list(raw.get("widgets") or [])
    novo = []
    substituido = False
    for w in widgets:
        d = w.get("definition") or {}
        title = d.get("title") if isinstance(d, dict) else None
        if w.get("id") == GROUP_PONTOS_CEGOS_ID or title == (
            "[Metricas] Chat / NF-e / Estoque / Telegram / Repricing"
        ):
            novo.append(_grupo_pontos_cegos())
            substituido = True
        else:
            novo.append(w)
    if not substituido:
        novo.append(_grupo_pontos_cegos())

    payload = {
        "title": raw["title"],
        "description": (
            "Saude + pontos cegos (chat/nfe/estoque/telegram/repricing). "
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
            "query": (
                "sum(last_24h):(sum:robo.ads.falha{*}.as_count() + "
                "sum:robo.ads.probe_falha{*}.as_count()) > 0"
            ),
            "message": "Falha no gatilho Product Ads (API/probe). Revise scopes advertising.\n" + msg_base,
            "tags": [TAG_MONITOR, "monitor:ads", "severity:p1"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 1,
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
            "message": "Busca de pedidos falhou — vendas podem nao ser notificadas no WhatsApp.\n" + msg_base,
            "tags": [TAG_MONITOR, "monitor:vendas", "severity:p1"],
            "options": {
                "thresholds": {"critical": 0},
                "notify_no_data": False,
                "require_full_window": False,
                "include_tags": True,
            },
            "priority": 1,
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
