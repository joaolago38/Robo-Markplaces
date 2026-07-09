"""
core/whatsapp.py
Envia mensagens via WhatsApp usando Evolution API ou WhatsApp Business Cloud.
Nunca lança exceção.
"""
from __future__ import annotations

import logging

from core.config import (
    WHATSAPP_API_TYPE,
    WHATSAPP_API_URL,
    WHATSAPP_API_KEY,
    WHATSAPP_GRUPO_MANICURES_ID,
    WHATSAPP_INSTANCE,
    WHATSAPP_NUMERO_DESTINO,
    WHATSAPP_BUSINESS_TOKEN,
    WHATSAPP_PHONE_ID,
)
from core.horario import formatar_data_hora_br
from core.http_client import request

logger = logging.getLogger("whatsapp")


def _api_type() -> str:
    return (WHATSAPP_API_TYPE or "evolution").strip().lower()


def _enabled() -> bool:
    """Verifica se WhatsApp está configurado."""
    t = _api_type()
    if t == "evolution":
        return bool(WHATSAPP_API_URL and WHATSAPP_API_KEY and WHATSAPP_INSTANCE)
    if t == "meta":
        return bool(WHATSAPP_BUSINESS_TOKEN and WHATSAPP_PHONE_ID)
    return False


def enviar_mensagem(numero: str, mensagem: str) -> bool:
    """
    Envia mensagem de texto para o número informado.
    numero: formato internacional sem + e sem espaços. Ex: 5519999889059
    Retorna True se enviado com sucesso, False caso contrário.
    Nunca lança exceção.
    """
    try:
        if not _enabled():
            logger.warning("WhatsApp não configurado — mensagem não enviada: %s", mensagem[:80])
            return False

        t = _api_type()
        if t == "evolution":
            return _enviar_evolution(numero, mensagem)
        if t == "meta":
            return _enviar_meta(numero, mensagem)

        logger.warning("WHATSAPP_API_TYPE inválido: %s", WHATSAPP_API_TYPE)
        return False
    except Exception as exc:
        logger.error("WhatsApp enviar_mensagem erro: %s", exc)
        return False


def enviar_mensagem_grupo(grupo_id: str, mensagem: str) -> bool:
    """
    Envia texto para grupo WhatsApp (Evolution API).
    grupo_id: JID do grupo, ex. 120363xxxxxxxx@g.us
    """
    grupo_id = (grupo_id or "").strip()
    if not grupo_id or not mensagem:
        return False
    if not _enabled():
        logger.warning("WhatsApp não configurado — grupo não receberá mensagem")
        return False
    if _api_type() != "evolution":
        logger.warning("Envio para grupo WhatsApp requer WHATSAPP_API_TYPE=evolution")
        return False
    return _enviar_evolution(grupo_id, mensagem)


def enviar_grupo_manicures(mensagem: str) -> bool:
    """Atalho: envia para WHATSAPP_GRUPO_MANICURES_ID."""
    gid = (WHATSAPP_GRUPO_MANICURES_ID or "").strip()
    if not gid:
        logger.warning("WHATSAPP_GRUPO_MANICURES_ID não configurado")
        return False
    return enviar_mensagem_grupo(gid, mensagem)


def whatsapp_grupo_manicures_configurado() -> bool:
    """True se API Evolution está pronta e há JID do grupo manicures."""
    return bool((WHATSAPP_GRUPO_MANICURES_ID or "").strip() and _enabled() and _api_type() == "evolution")


def _enviar_evolution(numero: str, mensagem: str) -> bool:
    """Envia via Evolution API (auto-hospedada)."""
    try:
        url = f"{WHATSAPP_API_URL.rstrip('/')}/message/sendText/{WHATSAPP_INSTANCE}"
        r = request(
            "POST",
            url,
            headers={
                "apikey": WHATSAPP_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "number": numero,
                "textMessage": {"text": mensagem},
                "options": {
                    "delay": 1000,
                    "presence": "composing",
                },
            },
            timeout=15,
        )
        r.raise_for_status()
        logger.info("WhatsApp Evolution enviado para %s", numero)
        return True
    except Exception as exc:
        logger.error("WhatsApp Evolution erro para %s: %s", numero, exc)
        return False


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
    """
    Envia notificação de nova venda para o número fixo configurado em
    WHATSAPP_NUMERO_DESTINO (padrão: 5519999889059).
    """
    hora = formatar_data_hora_br()

    emoji_marketplace = {
        "mercadolivre": "🛒",
        "shopee": "🛍️",
        "magalu": "🏪",
        "amazon": "📦",
    }.get(marketplace.lower(), "🏬")

    msg = (
        f"{emoji_marketplace} *Nova Venda — {marketplace.title()}*\n"
        f"🕐 {hora}\n\n"
        f"📦 Produto: {produto}\n"
        f"🔢 Qtd: {quantidade}\n"
        f"💰 Valor: R$ {valor:.2f}\n"
        f"🔖 Pedido: {pedido_id}"
    )

    destino = (WHATSAPP_NUMERO_DESTINO or "").strip().replace("+", "").replace(" ", "")
    if not destino:
        logger.warning("WHATSAPP_NUMERO_DESTINO vazio — venda não notificada")
        return False

    return enviar_mensagem(destino, msg)
