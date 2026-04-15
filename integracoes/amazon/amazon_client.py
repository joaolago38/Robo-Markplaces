"""
integracoes/amazon/amazon_client.py
Cliente básico da Amazon SP-API para mensagens de comprador.
"""
import logging

from core.config import AMAZON_ACCESS_TOKEN
from core.http_client import request
from core.marketplace_keepalive import registrar_acesso, dias_sem_acesso

logger = logging.getLogger("amazon_client")
BASE = "https://sellingpartnerapi-na.amazon.com"


def _enabled() -> bool:
    return bool(AMAZON_ACCESS_TOKEN)


def _h():
    return {
        "x-amz-access-token": AMAZON_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }


def listar_mensagens_nao_respondidas(limit: int = 20) -> list[dict]:
    if not _enabled():
        logger.warning("Amazon não configurado.")
        return []
    try:
        r = request(
            "GET",
            f"{BASE}/messaging/v1/customerMessages",
            headers=_h(),
            params={"status": "UNREAD", "pageSize": limit},
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("messages", [])
    except Exception as exc:
        logger.error("Amazon listar_mensagens_nao_respondidas erro: %s", exc)
        return []


def responder_mensagem(thread_id: str, texto: str) -> bool:
    if not _enabled():
        logger.warning("Amazon não configurado para responder mensagem.")
        return False
    try:
        r = request(
            "POST",
            f"{BASE}/messaging/v1/customerMessages/{thread_id}",
            headers=_h(),
            json={"message": texto},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Amazon responder_mensagem erro thread_id=%s: %s", thread_id, exc)
        return False


def obter_saude_conta() -> dict:
    if not _enabled():
        return {"configurado": False, "pendencias": 0, "claims_rate": 0.0, "dias_sem_acesso": 999}

    mensagens = listar_mensagens_nao_respondidas(limit=50)
    registrar_acesso("amazon")
    return {
        "configurado": True,
        "pendencias": len(mensagens),
        "claims_rate": 0.0,
        "dias_sem_acesso": dias_sem_acesso("amazon") or 0,
    }
