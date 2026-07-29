"""
core/http_client.py
Cliente HTTP compartilhado com retry e backoff para falhas transitórias.

Também é o ponto único de observabilidade Datadog para chamadas de API
de marketplace: TODA integração (Bling, ML, Magalu, Shopee, Amazon,
Meta...) passa por aqui via `request()`. Por isso, métricas de
latência e taxa de erro instrumentadas neste módulo cobrem todas as
integrações de uma vez, sem precisar tocar em cada client individual.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.datadog_metrics import gauge, incrementar
from core.log_opcional import (
    erro_opcional,
    host_scraper_veiculos,
    log_erros_veiculos_ativos,
)

logger = logging.getLogger("http_client")

_RETRY = Retry(
    total=3,
    connect=3,
    read=3,
    status=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"}),
    raise_on_status=False,
)
_ADAPTER = HTTPAdapter(max_retries=_RETRY)
_SESSION = requests.Session()
_SESSION.mount("http://", _ADAPTER)
_SESSION.mount("https://", _ADAPTER)


def _host_simplificado(url: str) -> str:
    try:
        return urlparse(url).netloc or "desconhecido"
    except Exception:
        return "desconhecido"


def _origem_http(host: str) -> str:
    """Classifica origem para facet de latência (api vs scraper vs ia)."""
    h = (host or "").lower()
    if host_scraper_veiculos(host):
        return "scraper"
    if "anthropic.com" in h:
        return "ia"
    if "telegram.org" in h or "api.telegram" in h:
        return "telegram"
    if "datadoghq" in h:
        return "datadog"
    return "api"


def _emitir_metricas_http(host: str, metodo: str, *, duracao_ms: float, status_tag: str) -> None:
    """
    Scrapers com log silenciado não entram na média de latência (evita
    inflar robo.http.latencia_ms com timeouts de HTML).
    """
    origem = _origem_http(host)
    if origem == "scraper" and not log_erros_veiculos_ativos():
        return
    tags_base = [f"host:{host}", f"method:{metodo}", f"origem:{origem}"]
    gauge("http.latencia_ms", duracao_ms, tags=[*tags_base, f"status:{status_tag}"])


def request(method: str, url: str, timeout: int = 15, **kwargs: Any) -> requests.Response:
    """
    Executa request com sessão compartilhada + política de retry.
    Emite (best-effort) métricas de latência e erro por host ao
    Datadog — nunca lança exceção por causa disso.
    """
    metodo = method.upper()
    host = _host_simplificado(url)
    origem = _origem_http(host)
    tags_base = [f"host:{host}", f"method:{metodo}", f"origem:{origem}"]
    inicio = time.monotonic()
    try:
        response = _SESSION.request(method=method, url=url, timeout=timeout, **kwargs)
    except Exception as exc:
        duracao_ms = (time.monotonic() - inicio) * 1000
        _emitir_metricas_http(host, metodo, duracao_ms=duracao_ms, status_tag="exception")
        if not (origem == "scraper" and not log_erros_veiculos_ativos()):
            incrementar("http.exception", tags=tags_base)
        # Scrapers de lojas (Leopardo etc.) falham com frequência por timeout/bloqueio —
        # não poluir Datadog enquanto LOG_ERROS_VEICULOS_SCRAPERS=0.
        if host_scraper_veiculos(host) and not log_erros_veiculos_ativos():
            erro_opcional(
                logger,
                False,
                "HTTP %s %s falhou: %s",
                metodo,
                host,
                exc,
                flag_hint="LOG_ERROS_VEICULOS_SCRAPERS",
                extra={"error_kind": type(exc).__name__, "error_message": str(exc)},
            )
        else:
            logger.error(
                "HTTP %s %s falhou: %s",
                metodo,
                host,
                exc,
                extra={"error_kind": type(exc).__name__, "error_message": str(exc)},
            )
        raise

    duracao_ms = (time.monotonic() - inicio) * 1000
    faixa_status = f"{response.status_code // 100}xx"
    _emitir_metricas_http(host, metodo, duracao_ms=duracao_ms, status_tag=faixa_status)
    if response.status_code >= 400:
        if not (origem == "scraper" and not log_erros_veiculos_ativos()):
            incrementar(
                "http.erro",
                tags=[*tags_base, f"status_code:{response.status_code}"],
            )
    return response
