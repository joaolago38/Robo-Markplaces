"""
integracoes/magalu/magalu_client.py
Cliente Magalu Seller API para perguntas e respostas.
"""
import logging

from core.config import MAGALU_ACCESS_TOKEN, MAGALU_MERCHANT_ID
from core.http_client import request
from core.marketplace_keepalive import registrar_acesso, dias_sem_acesso

logger = logging.getLogger("magalu_client")
BASE = "https://api.magalu.com"


def _enabled() -> bool:
    return bool(MAGALU_ACCESS_TOKEN and MAGALU_MERCHANT_ID)


def _h():
    return {
        "Authorization": f"Bearer {MAGALU_ACCESS_TOKEN}",
        "X-Seller-Id": str(MAGALU_MERCHANT_ID),
        "Content-Type": "application/json",
    }


def listar_perguntas_nao_respondidas(limit: int = 20) -> list[dict]:
    if not _enabled():
        logger.warning("Magalu não configurado.")
        return []
    try:
        r = request(
            "GET",
            f"{BASE}/seller/questions",
            headers=_h(),
            params={"status": "pending", "limit": limit},
            timeout=20,
        )
        r.raise_for_status()
        body = r.json()
        return body.get("data", body.get("items", []))
    except Exception as exc:
        logger.error("Magalu listar_perguntas_nao_respondidas erro: %s", exc)
        return []


def responder_pergunta(question_id: str, texto: str) -> bool:
    if not _enabled():
        logger.warning("Magalu não configurado para responder pergunta.")
        return False
    try:
        r = request(
            "POST",
            f"{BASE}/seller/questions/{question_id}/answer",
            headers=_h(),
            json={"text": texto},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Magalu responder_pergunta erro question_id=%s: %s", question_id, exc)
        return False


def manter_conta_ativa(limite_dias_sem_acesso: int = 5) -> dict:
    sem_acesso = dias_sem_acesso("magalu")
    if sem_acesso is not None and sem_acesso < 1:
        return {"ok": True, "marketplace": "magalu", "acao": "já acessado hoje", "dias_sem_acesso": sem_acesso}

    if not _enabled():
        return {
            "ok": False,
            "marketplace": "magalu",
            "acao": "não configurado",
            "dias_sem_acesso": sem_acesso if sem_acesso is not None else -1,
            "alerta": True,
        }

    try:
        r = request(
            "GET",
            f"{BASE}/seller/questions",
            headers=_h(),
            params={"limit": 1},
            timeout=20,
        )
        r.raise_for_status()
        registrar_acesso("magalu")
        sem_acesso_atual = dias_sem_acesso("magalu") or 0
        return {
            "ok": True,
            "marketplace": "magalu",
            "acao": "keepalive executado",
            "dias_sem_acesso": sem_acesso_atual,
            "alerta": sem_acesso_atual >= limite_dias_sem_acesso,
        }
    except Exception as exc:
        logger.error("Magalu manter_conta_ativa erro: %s", exc)
        sem_acesso_atual = dias_sem_acesso("magalu")
        return {
            "ok": False,
            "marketplace": "magalu",
            "acao": "falha no keepalive",
            "dias_sem_acesso": sem_acesso_atual if sem_acesso_atual is not None else -1,
            "alerta": True,
        }


def obter_saude_conta() -> dict:
    if not _enabled():
        return {"configurado": False, "pendencias": 0, "claims_rate": 0.0, "dias_sem_acesso": 999}

    perguntas = listar_perguntas_nao_respondidas(limit=50)
    registrar_acesso("magalu")

    return {
        "configurado": True,
        "pendencias": len(perguntas),
        "claims_rate": 0.0,
        "dias_sem_acesso": dias_sem_acesso("magalu") or 0,
    }
