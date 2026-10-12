"""
core/whatsapp.py
WhatsApp Business Cloud (Meta) para 1:1 opcional.
Criativos no grupo das manicures são postagem manual — sem Evolution.
Nunca lança exceção.
"""
from __future__ import annotations

import logging

from core.config import (
    WHATSAPP_API_TYPE,
    WHATSAPP_BUSINESS_TOKEN,
    WHATSAPP_PHONE_ID,
)
from core.http_client import request

logger = logging.getLogger("whatsapp")


def _api_type() -> str:
    t = (WHATSAPP_API_TYPE or "meta").strip().lower()
    if t == "evolution":
        return "off"
    return t


def _enabled() -> bool:
    if _api_type() != "meta":
        return False
    return bool(WHATSAPP_BUSINESS_TOKEN and WHATSAPP_PHONE_ID)


def enviar_mensagem(numero: str, mensagem: str) -> bool:
    """
    Envia texto 1:1 via Cloud API (Meta).
    numero: internacional sem + e sem espaços. Ex: 5519999889059
    """
    try:
        if not _enabled():
            logger.warning("WhatsApp Meta não configurado — mensagem não enviada: %s", mensagem[:80])
            return False
        return _enviar_meta(numero, mensagem)
    except Exception as exc:
        logger.error("WhatsApp enviar_mensagem erro: %s", exc)
        return False


def enviar_mensagem_grupo(grupo_id: str, mensagem: str) -> bool:
    """Grupo WhatsApp não é enviado pelo robô (postagem manual)."""
    logger.info("Envio a grupo WhatsApp desligado (sem Evolution) grupo=%s", (grupo_id or "")[:24])
    return False


def enviar_grupo_manicures(mensagem: str) -> bool:
    """Compat: criativo não vai ao grupo — postagem manual."""
    if mensagem:
        logger.info("Criativo WhatsApp não enviado pelo robô (postagem manual)")
    return False


def whatsapp_grupo_manicures_configurado() -> bool:
    """Sempre False: não há Evolution / envio automático ao grupo."""
    return False


def buscar_mensagens_grupo_recentes(
    grupo_id: str | None = None,
    *,
    limite: int = 30,
) -> list[dict]:
    """Inbox de grupo dependia da Evolution — não lê mais."""
    return []


def _enviar_meta(numero: str, mensagem: str) -> bool:
    """Envia via WhatsApp Business Cloud API (Meta)."""
    try:
        url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
        r = request(
            "POST",
            url,
            headers={
                "Authorization": f"Bearer {WHATSAPP_BUSINESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": numero,
                "type": "text",
                "text": {"body": mensagem},
            },
            timeout=15,
        )
        r.raise_for_status()
        logger.info("WhatsApp Meta enviado para %s", numero)
        return True
    except Exception as exc:
        logger.error("WhatsApp Meta erro para %s: %s", numero, exc)
        return False


def notificar_venda(
    marketplace: str,
    pedido_id: str,
    produto: str,
    valor: float,
    quantidade: int = 1,
) -> bool:
    """Compat: aviso de venda vai ao Telegram do gestor."""
    from core.notificador import notificar_venda_gestor

    return notificar_venda_gestor(
        marketplace=marketplace,
        pedido_id=pedido_id,
        produto=produto,
        valor=valor,
        quantidade=quantidade,
    )
