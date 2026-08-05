"""
core/log_opcional.py
Erros ruidosos (scrapers, Claude, tokens de marketplace) — silenciados no
Datadog por padrão. Só sobem como ERROR quando a flag estiver ligada.

Religar no .env / secrets do Actions:
  LOG_ERROS_VEICULOS_SCRAPERS=1
  LOG_ERROS_CLAUDE=1
  LOG_ERROS_BLING=1
  LOG_ERROS_TOKENS=1   # Magalu / Shopee / Amazon (credenciais / refresh)
  LOG_ERROS_PEDIDOS=1  # busca de pedidos FALHOU (margem / notificador)
  LOG_ERROS_PNCP=1     # timeouts/503 do PNCP (gov.br)
"""
from __future__ import annotations

import logging
from typing import Any


def _env_ligado(nome: str, padrao: str = "0") -> bool:
    import os

    return os.getenv(nome, padrao).strip().lower() in ("1", "true", "yes", "on")


def log_erros_veiculos_ativos() -> bool:
    return _env_ligado("LOG_ERROS_VEICULOS_SCRAPERS", "0")


def log_erros_claude_ativos() -> bool:
    return _env_ligado("LOG_ERROS_CLAUDE", "0")


def log_erros_bling_ativos() -> bool:
    return _env_ligado("LOG_ERROS_BLING", "0")


def log_erros_tokens_ativos() -> bool:
    """Magalu / Shopee / Amazon — credenciais ausentes ou refresh inválido."""
    return _env_ligado("LOG_ERROS_TOKENS", "0")


def log_erros_pedidos_ativos() -> bool:
    """Falha ao listar pedidos (monitor margem / notificador de vendas)."""
    return _env_ligado("LOG_ERROS_PEDIDOS", "0")


def log_erros_pncp_ativos() -> bool:
    """Timeouts/503 do PNCP (gov.br) — ruidoso; silenciado por padrão."""
    return _env_ligado("LOG_ERROS_PNCP", "0")


# Hosts dos scrapers de veículos (http_client silencia falhas de conexão quando off).
HOSTS_SCRAPERS_VEICULOS: frozenset[str] = frozenset(
    {
        "www.leopardoveiculos.com.br",
        "leopardoveiculos.com.br",
        "www.veiculosbatidos.com.br",
        "veiculosbatidos.com.br",
        "lucineiautomoveis.com.br",
        "www.lucineiautomoveis.com.br",
        "www.motorjanveiculos.com.br",
        "motorjanveiculos.com.br",
        "velozesbatidos.com.br",
        "www.velozesbatidos.com.br",
        "esperancabatidos.com.br",
        "www.esperancabatidos.com.br",
        "www.007batidos.com.br",
        "007batidos.com.br",
    }
)

HOSTS_PNCP: frozenset[str] = frozenset(
    {
        "pncp.gov.br",
        "www.pncp.gov.br",
    }
)


def host_scraper_veiculos(host: str) -> bool:
    h = (host or "").strip().lower()
    if not h:
        return False
    if h in HOSTS_SCRAPERS_VEICULOS:
        return True
    return any(h.endswith("." + d) or h == d for d in HOSTS_SCRAPERS_VEICULOS)


def host_pncp(host: str) -> bool:
    h = (host or "").strip().lower()
    if not h:
        return False
    if h in HOSTS_PNCP:
        return True
    return h.endswith(".pncp.gov.br")


def erro_opcional(
    logger: logging.Logger,
    ativo: bool,
    msg: str,
    *args: Any,
    flag_hint: str = "",
    **kwargs: Any,
) -> None:
    """logger.error se ativo; senão logger.debug (não sobe ao Datadog INFO+)."""
    if ativo:
        logger.error(msg, *args, **kwargs)
        return
    prefixo = f"[silenciado — {flag_hint}=1] " if flag_hint else "[silenciado] "
    logger.debug(prefixo + msg, *args, **kwargs)
