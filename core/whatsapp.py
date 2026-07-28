"""
core/whatsapp.py
Envia mensagens via WhatsApp usando Evolution API ou WhatsApp Business Cloud.
Nunca lança exceção.
"""
from __future__ import annotations

import logging

from core.config import (
    WHATSAPP_API_KEY,
    WHATSAPP_API_TYPE,
    WHATSAPP_API_URL,
    WHATSAPP_BUSINESS_TOKEN,
    WHATSAPP_GRUPO_MANICURES_ID,
    WHATSAPP_INSTANCE,
    WHATSAPP_NUMERO_DESTINO,
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


def buscar_mensagens_grupo_recentes(
    grupo_id: str | None = None,
    *,
    limite: int = 30,
) -> list[dict]:
    """
    Busca mensagens recentes do grupo via Evolution API.
    Degrade graceful: retorna [] se endpoint/instância não existir.
    Formato: [{id, texto, autor, canal, externo_id, criado_em}]
    """
    gid = (grupo_id or WHATSAPP_GRUPO_MANICURES_ID or "").strip()
    if not gid:
        return []
    if not _enabled() or _api_type() != "evolution":
        logger.info("buscar_mensagens_grupo_recentes: Evolution não configurado")
        return []
    try:
        base = WHATSAPP_API_URL.rstrip("/")
        headers = {
            "apikey": WHATSAPP_API_KEY,
            "Content-Type": "application/json",
        }
        # Evolution v2: POST /chat/findMessages/{instance}
        url = f"{base}/chat/findMessages/{WHATSAPP_INSTANCE}"
        payload = {
            "where": {"key": {"remoteJid": gid}},
            "limit": max(1, min(int(limite), 100)),
        }
        r = request("POST", url, headers=headers, json=payload, timeout=20)
        if getattr(r, "status_code", 0) in (404, 405):
            # tentativa alternativa (algumas builds)
            url_alt = f"{base}/chat/findMessages/{WHATSAPP_INSTANCE}/{gid}"
            r = request("GET", url_alt, headers=headers, timeout=20)
        if getattr(r, "status_code", 0) >= 400:
            logger.warning(
                "Evolution findMessages HTTP %s — inbox WA indisponível",
                getattr(r, "status_code", "?"),
            )
            return []
        data = r.json() if r.content else {}
        raw = data
        if isinstance(data, dict):
            raw = data.get("messages") or data.get("data") or data.get("records") or data
            if isinstance(raw, dict):
                raw = raw.get("records") or raw.get("messages") or []
        if not isinstance(raw, list):
            return []
        out: list[dict] = []
        for item in raw[: max(1, min(int(limite), 100))]:
            if not isinstance(item, dict):
                continue
            key = item.get("key") or {}
            msg = item.get("message") or {}
            texto = (
                msg.get("conversation")
                or (msg.get("extendedTextMessage") or {}).get("text")
                or item.get("text")
                or item.get("body")
                or ""
            )
            texto = str(texto).strip()
            if not texto:
                continue
            mid = str(key.get("id") or item.get("id") or "")
            autor = str(key.get("participant") or item.get("pushName") or item.get("author") or "")
            out.append(
                {
                    "id": mid,
                    "externo_id": mid or f"{gid}:{texto[:40]}",
                    "canal": "whatsapp",
                    "texto": texto,
                    "autor": autor,
                    "grupo_id": gid,
                    "criado_em": item.get("messageTimestamp") or item.get("timestamp"),
                }
            )
        return out
    except Exception as exc:
        logger.warning("buscar_mensagens_grupo_recentes erro: %s", exc)
        return []


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
