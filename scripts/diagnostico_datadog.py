"""
Diagnóstico rápido Datadog (intake métricas + opcional query).

Uso (local ou GitHub Actions):
  python scripts/diagnostico_datadog.py

Não imprime chaves. Exit 0 se intake de métrica retornar 2xx;
exit 1 se faltar DD_API_KEY ou intake falhar.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.config as cfg  # noqa: E402
from core.datadog_metrics import incrementar  # noqa: E402


def _mascara(valor: str) -> str:
    v = (valor or "").strip()
    if not v:
        return "(vazio)"
    return f"definida (len={len(v)})"


def main() -> int:
    print("=== Diagnóstico Datadog ===")
    print(f"DD_SITE              = {cfg.DD_SITE}")
    print(f"DD_ENV               = {cfg.DD_ENV}")
    print(f"DD_METRICS_ENABLED   = {cfg.DD_METRICS_ENABLED}")
    print(f"DD_LOGS_ENABLED      = {cfg.DD_LOGS_ENABLED}")
    print(f"DD_API_KEY           = {_mascara(cfg.DD_API_KEY)}")
    print(f"DD_APPLICATION_KEY   = {_mascara(cfg.DD_APPLICATION_KEY)}")

    if not cfg.DD_API_KEY:
        print("FALHA: DD_API_KEY ausente — GitHub Secret DD_API_KEY não chega ao job.")
        return 1

    site = cfg.DD_SITE
    if "us5" not in site and site not in ("datadoghq.com", "datadoghq.eu"):
        print(f"AVISO: DD_SITE incomum ({site}). Org do projeto costuma ser us5.datadoghq.com.")
    if site == "datadoghq.com":
        print(
            "AVISO: DD_SITE=datadoghq.com (US1). Dashboard em us5.datadoghq.com "
            "não verá essas métricas."
        )

    # Intake direto (mesmo endpoint do cliente) — confere HTTP sem depender de buffer.
    import requests

    url = f"https://api.{site}/api/v2/series"
    payload = {
        "series": [
            {
                "metric": "robo.diagnostico.ping",
                "type": 1,
                "points": [{"timestamp": int(time.time()), "value": 1.0}],
                "tags": [
                    f"env:{cfg.DD_ENV}",
                    "service:robo-markplaces",
                    "origem:diagnostico_datadog",
                ],
            }
        ]
    }
    try:
        resp = requests.post(
            url,
            headers={"DD-API-KEY": cfg.DD_API_KEY, "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=10,
        )
        print(f"Intake metricas HTTP {resp.status_code} -> {url}")
        if resp.status_code >= 300:
            print(f"Corpo (trecho): {(resp.text or '')[:200]}")
            return 1
    except Exception as exc:
        print(f"FALHA intake: {exc}")
        return 1

    # Tambem passa pelo modulo oficial (mesmo path do orquestrador).
    incrementar("diagnostico.ping", tags=["origem:diagnostico_datadog"])
    print("incrementar(robo.diagnostico.ping) chamado via core.datadog_metrics")

    if cfg.DD_APPLICATION_KEY:
        qurl = f"https://api.{site}/api/v1/query"
        try:
            q = requests.get(
                qurl,
                headers={
                    "DD-API-KEY": cfg.DD_API_KEY,
                    "DD-APPLICATION-KEY": cfg.DD_APPLICATION_KEY,
                },
                params={
                    "query": "sum:robo.orquestrador.ciclo{*}.as_count()",
                    "from": int(time.time()) - 3600 * 24,
                    "to": int(time.time()),
                },
                timeout=15,
            )
            print(f"Query orquestrador.ciclo HTTP {q.status_code}")
            if q.status_code == 403:
                print(
                    "Leitura bloqueada (403): Application Key / role sem metrics_read. "
                    "Intake pode estar OK e o dashboard ainda vazio."
                )
            elif q.status_code < 300:
                series = (q.json() or {}).get("series") or []
                print(f"Series retornadas (24h): {len(series)}")
                if not series:
                    print(
                        "Sem pontos em robo.orquestrador.ciclo nas ultimas 24h — "
                        "rode o workflow Orquestrador 30min ou confira se o "
                        "dashboard consulta esse nome (nao 'tarefas_*')."
                    )
        except Exception as exc:
            print(f"Query falhou (nao bloqueia intake): {exc}")
    else:
        print(
            "DD_APPLICATION_KEY ausente — nao da para consultar Metrics API. "
            "Crie o secret no GitHub (so leitura). Intake de metricas nao precisa dela."
        )

    print(
        "OK intake. No Metrics Explorer (site correto) busque: "
        "robo.diagnostico.ping / robo.orquestrador.ciclo / robo.orquestrador.agente.execucao"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
