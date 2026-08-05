"""
integracoes/licitacao/pncp_client.py
Cliente da API pública de consulta do PNCP (todos os estados).

- Sem retry urllib3 (timeout não melhora com 3 tentativas e polui Datadog)
- Circuit breaker: após N falhas na rodada, para de chamar a API
- Erros em debug por padrão (LOG_ERROS_PNCP=1 para subir ao Datadog)
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, timedelta
from typing import Any

import requests

from core.log_opcional import erro_opcional, log_erros_pncp_ativos

logger = logging.getLogger("licitacao_pncp")

BASE_URL = "https://pncp.gov.br/api/consulta/v1"

_LOCK = threading.Lock()
_falhas_seguidas = 0
_breaker_ate: float = 0.0
_breaker_aviso_enviado = False

# Sessão sem Retry — timeout/503 do gov.br não se resolvem com backoff curto.
_SESS = requests.Session()
_SESS.headers.update(
    {
        "Accept": "application/json",
        "User-Agent": "robo-markplaces-licitacoes/1.0",
    }
)


def _cfg() -> tuple[int, int, float]:
    from core.config import (
        LICITACOES_PNCP_BREAKER_SEG,
        LICITACOES_PNCP_FALHAS_PARA_BREAKER,
        LICITACOES_PNCP_TIMEOUT_SEG,
    )

    return (
        max(10, int(LICITACOES_PNCP_TIMEOUT_SEG or 30)),
        max(1, int(LICITACOES_PNCP_FALHAS_PARA_BREAKER or 3)),
        float(LICITACOES_PNCP_BREAKER_SEG or 900),
    )


def reset_breaker_para_teste() -> None:
    global _falhas_seguidas, _breaker_ate, _breaker_aviso_enviado
    with _LOCK:
        _falhas_seguidas = 0
        _breaker_ate = 0.0
        _breaker_aviso_enviado = False


def breaker_aberto() -> bool:
    with _LOCK:
        return time.monotonic() < _breaker_ate


def status_breaker() -> dict[str, Any]:
    with _LOCK:
        aberto = time.monotonic() < _breaker_ate
        return {
            "aberto": aberto,
            "falhas_seguidas": _falhas_seguidas,
            "restante_seg": max(0.0, _breaker_ate - time.monotonic()) if aberto else 0.0,
        }


def _abrir_breaker(limite: int, duracao: float) -> None:
    global _breaker_ate, _breaker_aviso_enviado
    _breaker_ate = time.monotonic() + duracao
    if not _breaker_aviso_enviado:
        _breaker_aviso_enviado = True
        logger.warning(
            "PNCP circuit breaker aberto após %s falha(s) — pausa %.0fs (site lento/503)",
            limite,
            duracao,
        )


def _registrar_ok() -> None:
    global _falhas_seguidas, _breaker_aviso_enviado
    with _LOCK:
        _falhas_seguidas = 0
        _breaker_aviso_enviado = False


def _registrar_falha() -> None:
    global _falhas_seguidas
    _timeout, limite, duracao = _cfg()
    with _LOCK:
        _falhas_seguidas += 1
        if _falhas_seguidas >= limite:
            _abrir_breaker(limite, duracao)


def _formatar_data(d: date) -> str:
    return d.strftime("%Y%m%d")


def _get_json(path: str, *, params: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
    if breaker_aberto():
        return {}

    to, _limite, _dur = _cfg()
    if timeout is not None:
        to = timeout

    try:
        r = _SESS.get(f"{BASE_URL}{path}", params=params, timeout=to)
    except Exception as exc:
        _registrar_falha()
        erro_opcional(
            logger,
            log_erros_pncp_ativos(),
            "PNCP %s erro: %s",
            path,
            exc,
            flag_hint="LOG_ERROS_PNCP",
            extra={"error_kind": type(exc).__name__, "error_message": str(exc)[:300]},
        )
        return {}

    if r.status_code == 503 or r.status_code >= 500:
        _registrar_falha()
        erro_opcional(
            logger,
            log_erros_pncp_ativos(),
            "PNCP %s status=%s body=%s",
            path,
            r.status_code,
            (r.text or "")[:200],
            flag_hint="LOG_ERROS_PNCP",
        )
        return {}

    if r.status_code != 200:
        # 4xx: não abre breaker (parâmetro/cliente)
        logger.debug("PNCP %s status=%s body=%s", path, r.status_code, (r.text or "")[:200])
        return {}

    try:
        body = r.json()
    except Exception as exc:
        _registrar_falha()
        erro_opcional(
            logger,
            log_erros_pncp_ativos(),
            "PNCP %s JSON inválido: %s",
            path,
            exc,
            flag_hint="LOG_ERROS_PNCP",
        )
        return {}

    _registrar_ok()
    return body if isinstance(body, dict) else {}


def buscar_propostas_abertas(
    *,
    codigo_modalidade: int,
    uf: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 50,
    dias_frente: int = 45,
) -> dict[str, Any]:
    """Contratações com recebimento de propostas em aberto."""
    hoje = date.today()
    params: dict[str, Any] = {
        "dataFinal": _formatar_data(hoje + timedelta(days=dias_frente)),
        "codigoModalidadeContratacao": codigo_modalidade,
        "pagina": max(1, pagina),
        "tamanhoPagina": max(10, min(50, tamanho_pagina)),
    }
    if uf:
        params["uf"] = uf.strip().upper()[:2]
    return _get_json("/contratacoes/proposta", params=params)


def buscar_publicacoes_recentes(
    *,
    codigo_modalidade: int,
    uf: str | None = None,
    pagina: int = 1,
    tamanho_pagina: int = 50,
    dias_atras: int = 7,
) -> dict[str, Any]:
    """Contratações publicadas recentemente."""
    hoje = date.today()
    params: dict[str, Any] = {
        "dataInicial": _formatar_data(hoje - timedelta(days=dias_atras)),
        "dataFinal": _formatar_data(hoje),
        "codigoModalidadeContratacao": codigo_modalidade,
        "pagina": max(1, pagina),
        "tamanhoPagina": max(10, min(50, tamanho_pagina)),
    }
    if uf:
        params["uf"] = uf.strip().upper()[:2]
    return _get_json("/contratacoes/publicacao", params=params)


def buscar_detalhe_compra(cnpj_orgao: str, ano: int, sequencial: int) -> dict[str, Any]:
    cnpj = "".join(c for c in str(cnpj_orgao) if c.isdigit())
    if not cnpj or not ano or not sequencial:
        return {}
    return _get_json(f"/orgaos/{cnpj}/compras/{int(ano)}/{int(sequencial)}", params={})
