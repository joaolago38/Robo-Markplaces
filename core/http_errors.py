"""
core/http_errors.py
Utilitários para logar erros HTTP sem mascarar como resultado vazio.
"""
from __future__ import annotations

import logging
import re


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
    """Registra ERROR quando uma leitura HTTP não retornou 200."""
    status = status_http(resposta)
    if status == 200:
        return
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
