"""
core/prontidao.py
Sinais de prontidão dos agentes: só notificar o Telegram quando houver
canal (Telegram) E fonte de dados configurados. Enquanto não houver
"sinalização de configuração", o agente não deve mandar mensagem.

Nunca lança exceção.
"""
from __future__ import annotations

import logging

from core.config import BRAVE_SEARCH_API_KEY
from core.notificador import gestor_telegram_configurado

logger = logging.getLogger("prontidao")


def ml_configurado() -> bool:
    """True se o Mercado Livre tem credenciais de runtime (token + seller)."""
    try:
        from integracoes.ml import ml_client

        return bool(ml_client._enabled())
    except Exception:
        return False


def brave_configurado() -> bool:
    """True se há chave da Brave Search API (busca web aberta)."""
    return bool((BRAVE_SEARCH_API_KEY or "").strip())


def fonte_esmaltes_configurada() -> bool:
    """
    True se existe ao menos uma fonte de dados utilizável para esmaltes:
    API do ML ou Brave Search. DDG puro (grátis/instável) não conta como
    "configuração" — é apenas melhor-esforço.
    """
    return ml_configurado() or brave_configurado()


def pode_alertar_esmaltes() -> tuple[bool, str]:
    """
    Retorna (pode_alertar, motivo).

    Só libera o envio quando o Telegram do gestor E uma fonte de dados
    estão configurados. Caso contrário devolve o motivo para log.
    """
    if not gestor_telegram_configurado():
        return False, "telegram_nao_configurado"
    if not fonte_esmaltes_configurada():
        return False, "fonte_dados_nao_configurada (defina ML_ACCESS_TOKEN/ML_SELLER_ID ou BRAVE_SEARCH_API_KEY)"
    return True, "ok"
