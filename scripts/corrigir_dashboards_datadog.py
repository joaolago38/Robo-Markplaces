"""
Corrige queries quebradas nos dashboards Datadog do Robo-Markplaces.

Problema: widgets de log usavam wildcards colados (*Orquestrador*iniciando*)
que nao batem no texto tokenizado. Troca por frases exatas + queries de metrica.

Requer no .env (ou ambiente):
  DD_API_KEY
  DD_APPLICATION_KEY   # leitura/escrita de dashboards
  DD_SITE=us5.datadoghq.com

Uso:
  python scripts/corrigir_dashboards_datadog.py
  python scripts/corrigir_dashboards_datadog.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Carrega .env sem sobrescrever env ja definido
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

DASHBOARDS = (
    "3iy-tka-awu",  # Saude de Integracoes e Orquestrador
    "7be-b7r-nrk",  # Operacao Marketplaces
)

# Ordem importa: padroes mais especificos primeiro.
_QUERY_REPLACES: list[tuple[str, str]] = [
    ("*Orquestrador*iniciando*", '"Orquestrador: iniciando"'),
    ("*finalizado*ok=True*", '"finalizado ok=True"'),
    ("*finalizado*ok=False*", '"finalizado ok=False"'),
    ("*ciclo*concluído*", '"ciclo concluído"'),
    ("*ciclo*concluido*", '"ciclo concluído"'),
    ("*Token*renovado*", '"Token renovado" OR "token renovado" OR "Token renovado"'),
    ("*token*expirado*", '"token expirado" OR "Token expirado"'),
    ("*circuit*breaker*", '"circuit breaker" OR circuit_breaker OR "circuit-breaker"'),
    ("*Conectividade*FALHOU*", '"Conectividade" AND FALHOU'),
    ("*Vigia*problemas*detectados*", '"Vigia" AND problemas'),
    ("*Claude*bloqueado*", '"Claude" AND (bloqueado OR pausado)'),
    ("*Claude*desligado*", '"Claude" AND (desligado OR "CLAUDE_ATIVO=0")'),
    ("*DDG*bloqueado*", "DDG AND (bloqueado OR 403)"),
    ("*DDG*HTTP*403*", "DDG AND 403"),
    ("*DDG*vazio*", "DDG AND (vazio OR vazia)"),
    ("*sem*resultados*", '"sem resultados" OR "nenhum resultado"'),
    ("*não*configurado*", '"não configurado" OR "nao configurado"'),
    ("*nao*configurado*", '"não configurado" OR "nao configurado"'),
    ("*Não*configurado*", '"não configurado" OR "nao configurado"'),
    ("*SSL* OR *CERTIFICATE_VERIFY_FAILED*", "SSL OR CERTIFICATE_VERIFY_FAILED"),
    (
        "*timed*out* OR *Read*timed*out* OR *ReadTimeoutError* OR *Max*retries*exceeded*",
        "timeout OR timed OR ReadTimeoutError OR \"Max retries\"",
    ),
    (
        "*timed*out* OR *ReadTimeoutError* OR *Max*retries*exceeded*",
        "timeout OR timed OR ReadTimeoutError OR \"Max retries\"",
    ),
    (
        "*SSL* OR *timed*out* OR *ReadTimeoutError* OR *Max*retries* OR *Conectividade*FALHOU* OR *indisponível*",
        "(SSL OR CERTIFICATE_VERIFY_FAILED OR timeout OR timed OR ReadTimeoutError OR FALHOU OR indispon)",
    ),
    (
        "*SSL* OR *timed*out* OR *ReadTimeoutError* OR *Max*retries* OR *Conectividade*FALHOU* OR *indisponivel*",
        "(SSL OR CERTIFICATE_VERIFY_FAILED OR timeout OR timed OR ReadTimeoutError OR FALHOU OR indispon)",
    ),
    ("*sem*resultados* OR *403*bloqueada*", '("sem resultados" OR "nenhum resultado" OR 403)'),
    ("*sem*resultados* OR *vazio*", '("sem resultados" OR vazio OR vazia)'),
    ("*DDG*bloqueado* OR *DDG*HTTP*403*", "(DDG AND (bloqueado OR 403))"),
    ("*DDG*bloqueado* OR *DDG*HTTP*403* OR *DDG*vazio*", "(DDG AND (bloqueado OR 403 OR vazio))"),
    (
        "*Claude*bloqueado* OR *Claude*desligado* OR *CLAUDE_ATIVO=0*",
        '("Claude" AND (bloqueado OR desligado OR pausado)) OR CLAUDE_ATIVO=0',
    ),
    (
        "*não*configurado* OR *nao*configurado* OR *Não*configurado*",
        '("não configurado" OR "nao configurado")',
    ),
    (
        "*não*configurado* OR *nao*configurado* OR *Claude*bloqueado* OR *Claude*desligado* OR *Vigia*problemas* OR *Conectividade*FALHOU* OR *Falha*sincronizar* OR *token*inválido* OR *invalid_grant*",
        '("não configurado" OR "nao configurado" OR Claude OR Vigia OR FALHOU OR sincronizar OR invalid_grant)',
    ),
]

# Metrica inventada / sem Agent → metrica real do robo
_METRIC_REPLACES: list[tuple[str, str]] = [
    ("avg:system.cpu.user{*}", "avg:robo.orquestrador.ciclo.agentes_ok{*}"),
]


def _headers() -> dict[str, str]:
    return {
        "DD-API-KEY": DD_API_KEY,
        "DD-APPLICATION-KEY": DD_APPLICATION_KEY,
        "Content-Type": "application/json",
    }


def _api(path: str) -> str:
    return f"https://api.{DD_SITE}{path}"


def _fixar_query(q: str) -> tuple[str, bool]:
    original = q
    mudou = False
    for velho, novo in _QUERY_REPLACES:
        if velho in q:
            q = q.replace(velho, novo)
            mudou = True
    for velho, novo in _METRIC_REPLACES:
        if velho in q:
            q = q.replace(velho, novo)
            mudou = True
    return q, mudou or q != original


def _walk_fix(obj: Any, stats: dict[str, int]) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("query", "query_string", "search") and isinstance(v, str):
                novo, mudou = _fixar_query(v)
                if mudou:
                    stats["queries"] += 1
                out[k] = novo
            elif k == "search" and isinstance(v, dict) and isinstance(v.get("query"), str):
                novo, mudou = _fixar_query(v["query"])
                if mudou:
                    stats["queries"] += 1
                out[k] = {**v, "query": novo}
            else:
                out[k] = _walk_fix(v, stats)
        return out
    if isinstance(obj, list):
        return [_walk_fix(x, stats) for x in obj]
    if isinstance(obj, str):
        # queries soltas em listas de strings (raro)
        novo, mudou = _fixar_query(obj)
        if mudou:
            stats["queries"] += 1
        return novo
    return obj


def get_dashboard(dash_id: str) -> dict[str, Any]:
    r = requests.get(_api(f"/api/v1/dashboard/{dash_id}"), headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def put_dashboard(dash_id: str, body: dict[str, Any]) -> dict[str, Any]:
    # PUT espera campos do dashboard (nao o wrapper completo da GET)
    payload = {
        "title": body["title"],
        "description": body.get("description") or "",
        "widgets": body["widgets"],
        "layout_type": body.get("layout_type") or "ordered",
        "template_variables": body.get("template_variables") or [],
        "notify_list": body.get("notify_list") or [],
        "reflow_type": body.get("reflow_type"),
        "tags": body.get("tags") or [],
    }
    # remove Nones
    payload = {k: v for k, v in payload.items() if v is not None}
    r = requests.put(
        _api(f"/api/v1/dashboard/{dash_id}"),
        headers=_headers(),
        data=json.dumps(payload),
        timeout=60,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"PUT {dash_id} HTTP {r.status_code}: {(r.text or '')[:500]}")
    return r.json()


def corrigir(dash_id: str, *, dry_run: bool) -> dict[str, Any]:
    raw = get_dashboard(dash_id)
    stats = {"queries": 0}
    fixed = _walk_fix(raw, stats)
    # Atualiza descricao do board de saude
    if dash_id == "3iy-tka-awu":
        fixed["description"] = (
            "Complemento ao dashboard principal. Monitora tokens/auth, APIs, "
            "orquestrador (logs + metricas robo.orquestrador.*), conectividade e Claude."
        )
    if dry_run:
        return {
            "id": dash_id,
            "title": fixed.get("title"),
            "queries_corrigidas": stats["queries"],
            "dry_run": True,
            "url": f"https://{DD_SITE.replace('datadoghq', 'datadoghq')}/dashboard/{dash_id}".replace(
                "api.", "app."
            )
            if False
            else f"https://us5.datadoghq.com/dashboard/{dash_id}",
        }
    put_dashboard(dash_id, fixed)
    return {
        "id": dash_id,
        "title": fixed.get("title"),
        "queries_corrigidas": stats["queries"],
        "dry_run": False,
        "url": f"https://us5.datadoghq.com/dashboard/{dash_id}",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DD_API_KEY:
        print("FALHA: DD_API_KEY ausente")
        return 1
    if not DD_APPLICATION_KEY:
        print(
            "FALHA: DD_APPLICATION_KEY ausente no .env.\n"
            "Copie a Application Key (GitHub Secret DD_APPLICATION_KEY) para o .env local:\n"
            "  DD_APPLICATION_KEY=...\n"
            "Ela precisa de permissao de leitura/escrita de dashboards."
        )
        return 1

    print(f"Site={DD_SITE} dry_run={args.dry_run}")
    resultados = []
    for dash_id in DASHBOARDS:
        try:
            out = corrigir(dash_id, dry_run=args.dry_run)
            resultados.append(out)
            print(
                f"OK {out['id']} ({out['title']}): "
                f"{out['queries_corrigidas']} queries "
                f"{'[dry-run]' if out['dry_run'] else 'atualizadas'} → {out['url']}"
            )
        except Exception as exc:
            print(f"ERRO {dash_id}: {exc}")
            return 1
    print(json.dumps(resultados, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
