"""
core/telegram_gate.py
Validação de token Telegram + circuit breaker para evitar spam de ERROR no Datadog.
"""
from __future__ import annotations

import logging
import re
import time

from core.config import TELEGRAM_CIRCUIT_BREAKER_SEG, TELEGRAM_TOKEN
from core.http_client import request
from core.http_errors import mascarar_url_telegram

logger = logging.getLogger("telegram_gate")

_TOKEN_FORMATO = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")

_token_valido_cache: bool | None = None
_bloqueado_ate: float = 0.0
_ultimo_log_bloqueio: float = 0.0


def token_formato_valido(token: str | None = None) -> bool:
    return bool(_TOKEN_FORMATO.match((token or TELEGRAM_TOKEN or "").strip()))


def verificar_token(*, token: str | None = None, forcar: bool = False) -> bool:
    """
    Valida token via getMe. Cacheia resultado OK na sessão.
    Em 404 abre circuit breaker (não tenta enviar de novo por N segundos).
    """
    global _token_valido_cache, _bloqueado_ate

    tok = (token or TELEGRAM_TOKEN or "").strip()
    if not tok:
        return False
    if time.time() < _bloqueado_ate:
        return False
    if _token_valido_cache is True and not forcar:
        return True
    if not token_formato_valido(tok):
        _marcar_invalido("formato de token inválido (esperado 123456:ABC...)")
        return False
    try:
        r = request(
            "GET",
            f"https://api.telegram.org/bot{tok}/getMe",
            timeout=15,
        )
        if r.status_code == 404:
            _marcar_invalido("HTTP 404 no getMe — token revogado ou incorreto")
            return False
        r.raise_for_status()
        body = r.json()
        if not body.get("ok"):
            _marcar_invalido("getMe retornou ok=false")
            return False
        _token_valido_cache = True
        return True
    except Exception as exc:
        err = mascarar_url_telegram(str(exc))
        if "404" in err:
            _marcar_invalido(f"getMe 404 — {err}")
            return False
        logger.warning("Telegram getMe falhou (rede?): %s", err)
        return False


def pode_enviar(token: str | None = None) -> bool:
    """True se não há circuit breaker ativo e token parece válido."""
    if time.time() < _bloqueado_ate:
        return False
    if _token_valido_cache is False:
        return False
    return bool((token or TELEGRAM_TOKEN or "").strip())


def registrar_falha_envio(erro: str) -> None:
    if "404" in erro:
        _marcar_invalido("sendMessage HTTP 404")


def _marcar_invalido(motivo: str) -> None:
    global _token_valido_cache, _bloqueado_ate, _ultimo_log_bloqueio
    _token_valido_cache = False
    _bloqueado_ate = time.time() + TELEGRAM_CIRCUIT_BREAKER_SEG
    agora = time.time()
    if agora - _ultimo_log_bloqueio > 300:
        _ultimo_log_bloqueio = agora
        logger.error(
            "Telegram bloqueado por %ss — %s. Regenere token no @BotFather e "
            "atualize TELEGRAM_TOKEN nos secrets do GitHub Actions e no .env local. "
            "Diagnóstico: python scripts/diagnostico_telegram.py",
            TELEGRAM_CIRCUIT_BREAKER_SEG,
            motivo,
        )


def reset() -> None:
    """Somente para testes."""
    global _token_valido_cache, _bloqueado_ate, _ultimo_log_bloqueio
    _token_valido_cache = None
    _bloqueado_ate = 0.0
    _ultimo_log_bloqueio = 0.0
