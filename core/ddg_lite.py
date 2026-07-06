"""
core/ddg_lite.py
Cliente compartilhado DuckDuckGo com rate limit, retry e circuit breaker.
Usado por leilões e Alibaba para evitar HTTP 403 em rajada.

Padrão: GET em lite.duckduckgo.com (mais leve que POST html.duckduckgo.com).
Fallback automático para html quando DDG_BACKEND=auto.
"""
from __future__ import annotations

import logging
import re
import time
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

import requests as _requests

logger = logging.getLogger("ddg_lite")

_DDG_LITE = "https://lite.duckduckgo.com/lite/"
_DDG_HTML = "https://html.duckduckgo.com/html/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_DDG_SESSION = _requests.Session()

_ultima_requisicao = 0.0
_breaker_ate_por_contexto: dict[str, float] = {}
_falhas_por_contexto: dict[str, int] = {}


def _ctx(contexto: str) -> str:
    return (contexto or "geral").strip() or "geral"


def _headers(*, referer: str = "https://lite.duckduckgo.com/") -> dict[str, str]:
    return {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
    }


def _decodificar_url_ddg(href: str) -> str:
    href = unescape((href or "").strip())
    if href.startswith("//"):
        href = f"https:{href}"
    if "uddg=" in href:
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        return unquote((qs.get("uddg") or [href])[0])
    return href


def circuit_breaker_ativo(contexto: str = "geral") -> bool:
    """True se o circuit breaker DDG está bloqueando buscas no contexto."""
    return time.time() < _breaker_ate_por_contexto.get(_ctx(contexto), 0.0)


def segundos_restantes_circuit_breaker(contexto: str = "geral") -> int:
    """Segundos até o circuit breaker expirar (0 se inativo)."""
    if not circuit_breaker_ativo(contexto):
        return 0
    return max(0, int(_breaker_ate_por_contexto.get(_ctx(contexto), 0.0) - time.time()))


def mensagem_circuit_breaker(contexto: str = "geral") -> str | None:
    """Texto para logs de agentes quando não há resultados por bloqueio DDG."""
    if not circuit_breaker_ativo(contexto):
        return None
    return f"DDG circuit breaker ativo — liberação em ~{segundos_restantes_circuit_breaker(contexto)}s"


def extrair_resultados(html: str) -> list[dict[str, str]]:
    """Parser do endpoint html.duckduckgo.com (POST)."""
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
        titulo = unescape(re.sub(r"<[^>]+>", "", titulo_m.group(2))).strip()
        url = _decodificar_url_ddg(titulo_m.group(1))
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


def extrair_resultados_lite(html: str) -> list[dict[str, str]]:
    """Parser do endpoint lite.duckduckgo.com (GET)."""
    resultados: list[dict[str, str]] = []
    if not html:
        return resultados

    links = list(
        re.finditer(
            r"class=['\"]result-link['\"][^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
            html,
            re.DOTALL | re.IGNORECASE,
        )
    )
    if not links:
        links = list(
            re.finditer(
                r"href=['\"]([^'\"]+)['\"][^>]*class=['\"]result-link['\"][^>]*>(.*?)</a>",
                html,
                re.DOTALL | re.IGNORECASE,
            )
        )
    snippets = [
        unescape(re.sub(r"<[^>]+>", "", s)).strip()
        for s in re.findall(
            r"class=['\"]result-snippet['\"][^>]*>(.*?)</td>",
            html,
            re.DOTALL | re.IGNORECASE,
        )
    ]

    for i, match in enumerate(links):
        titulo = unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
        url = _decodificar_url_ddg(match.group(1))
        if not url.startswith("http"):
            trecho = html[match.end() : match.end() + 1200]
            link_text = re.search(
                r"class=['\"]link-text['\"][^>]*>([^<]+)</span>",
                trecho,
                re.IGNORECASE,
            )
            if link_text:
                url = link_text.group(1).strip()
                if not url.startswith("http"):
                    url = f"https://{url.lstrip('/')}"
        snippet = snippets[i] if i < len(snippets) else ""
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


def _abrir_circuit_breaker(segundos: float, motivo: str, contexto: str) -> None:
    c = _ctx(contexto)
    _breaker_ate_por_contexto[c] = time.time() + segundos
    _falhas_por_contexto[c] = 0
    logger.warning(
        "DDG circuit breaker %ss [%s] — %s (próximas buscas neste contexto retornam vazio até expirar)",
        int(segundos),
        c,
        motivo,
    )


def _ddg_request(method: str, url: str, **kwargs: object) -> _requests.Response:
    """
    Request DDG com sessão dedicada — sem retry urllib3 do http_client.
    Evita rajada de conexões (3× urllib3 × 3× ddg) que gera HTTPSConnectionPool no Datadog.
    """
    kwargs.setdefault("timeout", 20)
    if "headers" not in kwargs:
        kwargs["headers"] = _headers()
    return _DDG_SESSION.request(method, url, **kwargs)


def _buscar_lite(query: str) -> tuple[int, list[dict[str, str]]]:
    r = _ddg_request(
        "GET",
        _DDG_LITE,
        params={"q": query, "kl": "br-pt"},
        headers=_headers(referer="https://lite.duckduckgo.com/"),
    )
    if r.status_code >= 400:
        return r.status_code, []
    return r.status_code, extrair_resultados_lite(r.text or "")


def _buscar_html(query: str) -> tuple[int, list[dict[str, str]]]:
    r = _ddg_request(
        "POST",
        _DDG_HTML,
        data={"q": query, "kl": "br-pt"},
        headers={
            **_headers(referer="https://duckduckgo.com/"),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    if r.status_code >= 400:
        return r.status_code, []
    return r.status_code, extrair_resultados(r.text or "")


def _registrar_falha(status: int | None, contexto: str, query: str) -> bool:
    """Incrementa falhas do contexto; retorna True se abriu circuit breaker."""
    from core.config import DDG_CIRCUIT_BREAKER_SEG, DDG_FALHAS_403_PARA_BREAKER

    c = _ctx(contexto)
    if status in (403, 429) or status is None:
        _falhas_por_contexto[c] = _falhas_por_contexto.get(c, 0) + 1
        if _falhas_por_contexto[c] >= DDG_FALHAS_403_PARA_BREAKER:
            _abrir_circuit_breaker(
                DDG_CIRCUIT_BREAKER_SEG,
                f"{_falhas_por_contexto[c]} falhas seguidas",
                contexto,
            )
            return True
    return False


def _reset_falhas_contexto(contexto: str) -> None:
    _falhas_por_contexto[_ctx(contexto)] = 0


def buscar(query: str, *, max_resultados: int = 8, contexto: str = "geral") -> list[dict[str, str]]:
    """
    Busca no DuckDuckGo. Rate limit global + retry + circuit breaker.
    Nunca lança exceção.
    """
    from core.config import DDG_BACKEND, DDG_DISABLED, DDG_RETRY_BASE_SEG, DDG_RETRY_MAX

    if DDG_DISABLED:
        logger.info("DDG desabilitado [%s] — query=%r", contexto, query[:80])
        return []

    if circuit_breaker_ativo(contexto):
        logger.info(
            "DDG bloqueado [%s] — circuit breaker, faltam %ss — query=%r",
            contexto,
            segundos_restantes_circuit_breaker(contexto),
            query[:80],
        )
        return []

    backend = (DDG_BACKEND or "lite").lower()
    tentativas = max(1, DDG_RETRY_MAX)

    for n in range(tentativas):
        try:
            _aguardar_intervalo()
            status_final: int | None = None
            resultados: list[dict[str, str]] = []

            if backend in ("lite", "auto"):
                status, resultados = _buscar_lite(query)
                status_final = status
                if resultados:
                    _reset_falhas_contexto(contexto)
                    logger.debug(
                        "DDG lite OK [%s] — %s resultados — query=%r",
                        contexto,
                        len(resultados),
                        query[:80],
                    )
                    return resultados[:max_resultados]
                if backend == "lite" and status < 400:
                    logger.info(
                        "DDG lite vazio [%s] — query=%r",
                        contexto,
                        query[:80],
                    )
                    return []

            if backend in ("html", "auto"):
                status, resultados = _buscar_html(query)
                status_final = status
                if resultados:
                    _reset_falhas_contexto(contexto)
                    logger.debug(
                        "DDG html OK [%s] — %s resultados — query=%r",
                        contexto,
                        len(resultados),
                        query[:80],
                    )
                    return resultados[:max_resultados]

            if status_final in (403, 429):
                if _registrar_falha(status_final, contexto, query):
                    return []
                if n + 1 < tentativas:
                    espera = DDG_RETRY_BASE_SEG * (2**n)
                    logger.info(
                        "DDG HTTP %s [%s] — retry %s/%s em %.0fs",
                        status_final,
                        contexto,
                        n + 2,
                        tentativas,
                        espera,
                    )
                    time.sleep(espera)
                    continue
                logger.warning(
                    "DDG HTTP %s [%s] após %s tentativas — query=%r",
                    status_final,
                    contexto,
                    tentativas,
                    query[:80],
                )
                return []

            if status_final is not None and status_final >= 400:
                logger.warning(
                    "DDG HTTP %s [%s] query=%r",
                    status_final,
                    contexto,
                    query[:80],
                )
                return []

            _reset_falhas_contexto(contexto)
            return []

        except Exception as exc:
            if _registrar_falha(None, contexto, query):
                logger.error("DDG falhou [%s]: %s — circuit breaker aberto", contexto, exc)
                return []
            if n + 1 < tentativas:
                espera = DDG_RETRY_BASE_SEG * (2**n)
                logger.info(
                    "DDG erro [%s] — retry %s/%s em %.0fs: %s",
                    contexto,
                    n + 2,
                    tentativas,
                    espera,
                    exc,
                )
                time.sleep(espera)
                continue
            logger.error("DDG falhou [%s]: %s", contexto, exc)
            return []
    return []


def reset_circuit_breaker() -> None:
    """Somente para testes."""
    global _ultima_requisicao
    _breaker_ate_por_contexto.clear()
    _falhas_por_contexto.clear()
    _ultima_requisicao = 0.0
