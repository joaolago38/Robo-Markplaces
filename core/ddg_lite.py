"""
core/ddg_lite.py
Cliente compartilhado DuckDuckGo HTML com rate limit, retry e circuit breaker.
Usado por leilões e Alibaba para evitar HTTP 403 em rajada.
"""
from __future__ import annotations

import logging
import re
import time
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

from core.http_client import request

logger = logging.getLogger("ddg_lite")

_DDG_HTML = "https://html.duckduckgo.com/html/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_ultima_requisicao = 0.0
_circuit_breaker_ate = 0.0
_falhas_403_consecutivas = 0


def _headers() -> dict[str, str]:
    return {
        "User-Agent": _USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://duckduckgo.com/",
    }


def circuit_breaker_ativo() -> bool:
    """True se o circuit breaker DDG está bloqueando buscas."""
    return time.time() < _circuit_breaker_ate


def segundos_restantes_circuit_breaker() -> int:
    """Segundos até o circuit breaker expirar (0 se inativo)."""
    if not circuit_breaker_ativo():
        return 0
    return max(0, int(_circuit_breaker_ate - time.time()))


def mensagem_circuit_breaker() -> str | None:
    """Texto para logs de agentes quando não há resultados por bloqueio DDG."""
    if not circuit_breaker_ativo():
        return None
    return f"DDG circuit breaker ativo — liberação em ~{segundos_restantes_circuit_breaker()}s"


def extrair_resultados(html: str) -> list[dict[str, str]]:
    resultados: list[dict[str, str]] = []
    if not html:
        return resultados
    blocos = re.split(r'class="result\s', html)
    for bloco in blocos[1:]:
        titulo_m = re.search(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            bloco,
            re.DOTALL | re.IGNORECASE,
        )
        if not titulo_m:
            continue
        href_bruto = unescape(titulo_m.group(1))
        titulo = re.sub(r"<[^>]+>", "", titulo_m.group(2))
        titulo = unescape(titulo).strip()
        url = href_bruto
        if "uddg=" in href_bruto:
            parsed = urlparse(href_bruto)
            qs = parse_qs(parsed.query)
            url = unquote((qs.get("uddg") or [href_bruto])[0])
        snippet_m = re.search(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>',
            bloco,
            re.DOTALL | re.IGNORECASE,
        )
        snippet = ""
        if snippet_m:
            snippet = unescape(re.sub(r"<[^>]+>", "", snippet_m.group(1))).strip()
        if url.startswith("http"):
            resultados.append({"titulo": titulo, "url": url, "snippet": snippet})
    return resultados


def _aguardar_intervalo() -> None:
    from core.config import DDG_MIN_INTERVAL_SEG

    global _ultima_requisicao
    agora = time.monotonic()
    falta = DDG_MIN_INTERVAL_SEG - (agora - _ultima_requisicao)
    if falta > 0:
        time.sleep(falta)
    _ultima_requisicao = time.monotonic()


def _abrir_circuit_breaker(segundos: float, motivo: str) -> None:
    global _circuit_breaker_ate, _falhas_403_consecutivas
    _circuit_breaker_ate = time.time() + segundos
    _falhas_403_consecutivas = 0
    logger.warning(
        "DDG circuit breaker %ss — %s (próximas buscas retornam vazio até expirar)",
        int(segundos),
        motivo,
    )


def buscar(query: str, *, max_resultados: int = 8, contexto: str = "geral") -> list[dict[str, str]]:
    """
    Busca no DuckDuckGo Lite. Rate limit global + retry + circuit breaker em 403.
    Nunca lança exceção.
    """
    from core.config import (
        DDG_CIRCUIT_BREAKER_SEG,
        DDG_FALHAS_403_PARA_BREAKER,
        DDG_RETRY_BASE_SEG,
        DDG_RETRY_MAX,
    )

    global _falhas_403_consecutivas

    if circuit_breaker_ativo():
        logger.info(
            "DDG bloqueado [%s] — circuit breaker, faltam %ss — query=%r",
            contexto,
            segundos_restantes_circuit_breaker(),
            query[:80],
        )
        return []

    tentativas = max(1, DDG_RETRY_MAX)
    for n in range(tentativas):
        try:
            _aguardar_intervalo()
            r = request(
                "POST",
                _DDG_HTML,
                data={"q": query, "kl": "br-pt"},
                headers=_headers(),
                timeout=20,
            )
            if r.status_code in (403, 429):
                _falhas_403_consecutivas += 1
                if _falhas_403_consecutivas >= DDG_FALHAS_403_PARA_BREAKER:
                    _abrir_circuit_breaker(
                        DDG_CIRCUIT_BREAKER_SEG,
                        f"{_falhas_403_consecutivas} falhas 403/429 seguidas ({contexto})",
                    )
                    return []
                if n + 1 < tentativas:
                    espera = DDG_RETRY_BASE_SEG * (2**n)
                    logger.info(
                        "DDG HTTP %s [%s] — retry %s/%s em %.0fs",
                        r.status_code,
                        contexto,
                        n + 2,
                        tentativas,
                        espera,
                    )
                    time.sleep(espera)
                    continue
                logger.warning(
                    "DDG HTTP %s [%s] após %s tentativas — query=%r",
                    r.status_code,
                    contexto,
                    tentativas,
                    query[:80],
                )
                return []
            if r.status_code >= 400:
                logger.warning("DDG HTTP %s [%s] query=%r", r.status_code, contexto, query[:80])
                return []
            _falhas_403_consecutivas = 0
            return extrair_resultados(r.text)[:max_resultados]
        except Exception as exc:
            if n + 1 < tentativas:
                time.sleep(DDG_RETRY_BASE_SEG)
                continue
            logger.error("DDG falhou [%s]: %s", contexto, exc)
            return []
    return []


def reset_circuit_breaker() -> None:
    """Somente para testes."""
    global _circuit_breaker_ate, _falhas_403_consecutivas, _ultima_requisicao
    _circuit_breaker_ate = 0.0
    _falhas_403_consecutivas = 0
    _ultima_requisicao = 0.0
