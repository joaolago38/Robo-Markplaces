"""
core/http_errors.py
Utilitários para logar erros HTTP sem mascarar como resultado vazio.
"""
from __future__ import annotations

import logging
import re

from core.datadog_metrics import incrementar


def status_http(resposta) -> int:
    """Retorna status HTTP inteiro; mocks sem status_code explícito tratados como 200."""
    status = getattr(resposta, "status_code", None)
    if isinstance(status, int):
        return status
    return 200


def trecho_corpo(resposta, limite: int = 200) -> str:
    texto = getattr(resposta, "text", "") or ""
    if not isinstance(texto, str):
        texto = str(texto)
    return texto[:limite].replace("\n", " ").strip()


def log_http_erro_listagem(logger: logging.Logger, contexto: str, resposta) -> None:
    """Registra ERROR quando uma leitura HTTP não retornou 200.

    Também incrementa `robo.dados.degradado` no Datadog: sem isso, uma
    listagem que falhou (token expirado, sem permissão, etc.) e caiu de
    volta para lista vazia é, hoje, indistinguível — em logs e métricas —
    de uma listagem que teve sucesso e genuinamente não encontrou nada.
    """
    status = status_http(resposta)
    if status == 200:
        return
    incrementar("dados.degradado", tags=[f"contexto:{contexto}", f"status_code:{status}"])
    corpo = trecho_corpo(resposta)
    if status == 403:
        logger.error(
            "%s HTTP 403 — provável falta de ESCOPO/permissão "
            "(não apenas token expirado): %s",
            contexto,
            corpo,
        )
    elif status == 401:
        logger.error("%s HTTP 401 — token inválido ou expirado: %s", contexto, corpo)
    else:
        logger.error("%s HTTP %s: %s", contexto, status, corpo)


def mascarar_url_telegram(texto: str) -> str:
    """Remove o token do bot de URLs/logs do Telegram."""
    if not texto:
        return texto
    return re.sub(r"(api\.telegram\.org/bot)[^/\s]+", r"\1***", str(texto))


def mascarar_segredos_http(texto: str) -> str:
    """Redige tokens em query strings / URLs / headers de logs de erro HTTP."""
    if not texto:
        return texto
    t = mascarar_url_telegram(str(texto))
    t = re.sub(r"(access_token=)[^&\s\"']+", r"\1***", t, flags=re.IGNORECASE)
    t = re.sub(r"(refresh_token=)[^&\s\"']+", r"\1***", t, flags=re.IGNORECASE)
    t = re.sub(r"(partner_key=)[^&\s\"']+", r"\1***", t, flags=re.IGNORECASE)
    t = re.sub(r"(api[_-]?key=)[^&\s\"']+", r"\1***", t, flags=re.IGNORECASE)
    t = re.sub(
        r"(Authorization:\s*Bearer\s+)[^\s\"']+",
        r"\1***",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(
        r"(x-api-key[\"']?\s*[:=]\s*[\"']?)[^\"'\s,]+",
        r"\1***",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"(sk-ant-[A-Za-z0-9_-]+)", "sk-ant-***", t)
    return t
