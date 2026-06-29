"""
core/datadog_metrics.py
Cliente leve para enviar métricas customizadas ao Datadog via Metrics
API v2 (POST /api/v2/series) — HTTP direto, sem Agent, no mesmo
espírito de core/datadog_logger.py. Nunca lança exceção: falha de rede
no envio de métrica não pode derrubar a aplicação.

Tipos suportados (enum MetricIntakeType da API v2 do Datadog):
  1 = count  -> use incrementar() para eventos/ocorrências
  3 = gauge  -> use gauge() para latência, saldo, quantidade atual
"""
from __future__ import annotations

import contextlib
import json
import time

import requests

_TYPE_COUNT = 1
_TYPE_GAUGE = 3

# Prefixo de todas as métricas deste robô — facilita achar tudo no
# Metrics Explorer do Datadog digitando "robo.".
_PREFIXO = "robo"


def _enviar(nome: str, valor: float, tipo: int, tags: list[str] | None = None) -> None:
    from core.config import DD_API_KEY, DD_ENV, DD_LOGS_ENABLED, DD_SITE

    if not DD_LOGS_ENABLED or not DD_API_KEY:
        return
    try:
        url = f"https://api.{DD_SITE}/api/v2/series"
        ponto = {
            "metric": f"{_PREFIXO}.{nome}",
            "type": tipo,
            "points": [{"timestamp": int(time.time()), "value": float(valor)}],
            "tags": [f"env:{DD_ENV}", *(tags or [])],
        }
        requests.post(
            url,
            headers={"DD-API-KEY": DD_API_KEY, "Content-Type": "application/json"},
            data=json.dumps({"series": [ponto]}),
            timeout=3,
        )
    except Exception:
        pass


def incrementar(nome: str, valor: float = 1.0, tags: list[str] | None = None) -> None:
    """Métrica do tipo count — ex.: NF-e emitida, token renovado, erro de API."""
    _enviar(nome, valor, _TYPE_COUNT, tags)


def gauge(nome: str, valor: float, tags: list[str] | None = None) -> None:
    """Métrica do tipo gauge — ex.: latência em ms, tokens consumidos no momento."""
    _enviar(nome, valor, _TYPE_GAUGE, tags)


@contextlib.contextmanager
def medir_latencia(nome: str, tags: list[str] | None = None):
    """Context manager: mede a duração do bloco `with` e envia como gauge em ms.

    Uso:
        with medir_latencia("ml.listar_produtos", tags=["marketplace:mercadolivre"]):
            ... chamada à API ...
    """
    inicio = time.monotonic()
    try:
        yield
    finally:
        duracao_ms = (time.monotonic() - inicio) * 1000
        gauge(f"{nome}.latencia_ms", duracao_ms, tags)
