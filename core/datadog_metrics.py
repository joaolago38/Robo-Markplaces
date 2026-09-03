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
import logging
import os
import re
import time

import requests

_TYPE_COUNT = 1
_TYPE_GAUGE = 3

# Prefixo de todas as métricas deste robô — facilita achar tudo no
# Metrics Explorer do Datadog digitando "robo.".
_PREFIXO = "robo"

# Tags de alta cardinalidade — descartadas no envio (detalhe fica no log).
_TAGS_BLOQUEADAS_PREFIXOS = (
    "sku:",
    "termo:",
    "item:",
    "veiculo:",
    "novos:",
    "falhas:",
)

logger = logging.getLogger("datadog_metrics")
_falhas_envio = 0
_ultimo_aviso_falha_ts = 0.0


def falhas_envio() -> int:
    """Contador local de falhas de ingest (útil em testes/diagnóstico)."""
    return _falhas_envio


def reset_falhas_envio() -> None:
    global _falhas_envio, _ultimo_aviso_falha_ts
    _falhas_envio = 0
    _ultimo_aviso_falha_ts = 0.0


def tag_produto(valor: str) -> str | None:
    """Tag produto: de baixa cardinalidade (termo: é descartado no envio)."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(valor or "").strip().lower()).strip("-")[:40]
    return f"produto:{slug}" if slug else None


def _sanitizar_tags(tags: list[str] | None) -> list[str]:
    out: list[str] = []
    for raw in tags or []:
        t = str(raw or "").strip()
        if not t or ":" not in t:
            continue
        low = t.lower()
        if any(low.startswith(p) for p in _TAGS_BLOQUEADAS_PREFIXOS):
            continue
        # Evita valores enormes em tags
        if len(t) > 120:
            t = t[:117] + "..."
        out.append(t)
    return out


def _avisar_falha(motivo: str) -> None:
    global _falhas_envio, _ultimo_aviso_falha_ts
    _falhas_envio += 1
    agora = time.monotonic()
    # Rate-limit: no máx. 1 aviso a cada 60s (evita flood se DD cair)
    if agora - _ultimo_aviso_falha_ts < 60:
        return
    _ultimo_aviso_falha_ts = agora
    logger.warning(
        "Datadog metrics envio falhou (%s falha(s) desde o start): %s",
        _falhas_envio,
        motivo,
    )


def _enviar(nome: str, valor: float, tipo: int, tags: list[str] | None = None) -> None:
    from core.config import DD_API_KEY, DD_ENV, DD_METRICS_ENABLED, DD_SITE

    if not DD_METRICS_ENABLED or not DD_API_KEY:
        return
    # Suíte local não deve POST na API (SSL/timeout trava pytest). O cliente
    # em si é coberto em tests/test_datadog_metrics.py com requests mockado.
    pytest_atual = os.environ.get("PYTEST_CURRENT_TEST") or ""
    if pytest_atual and "test_datadog_metrics.py" not in pytest_atual:
        return
    try:
        url = f"https://api.{DD_SITE}/api/v2/series"
        ponto = {
            "metric": f"{_PREFIXO}.{nome}",
            "type": tipo,
            "points": [{"timestamp": int(time.time()), "value": float(valor)}],
            "tags": [
                f"env:{DD_ENV}",
                "service:robo-markplaces",
                *_sanitizar_tags(tags),
            ],
        }
        resp = requests.post(
            url,
            headers={"DD-API-KEY": DD_API_KEY, "Content-Type": "application/json"},
            data=json.dumps({"series": [ponto]}),
            timeout=3,
            verify=os.getenv("DD_SSL_VERIFY", "1").strip().lower() not in ("0", "false", "no"),
        )
        status = getattr(resp, "status_code", 0)
        if isinstance(status, int) and status >= 300:
            _avisar_falha(f"HTTP {status}")
    except Exception as exc:
        _avisar_falha(str(exc)[:160])


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
