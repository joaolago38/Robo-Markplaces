"""
integracoes/ml/ml_client.py
Cliente Mercado Livre com operações essenciais de perguntas/respostas.
"""
import logging

from core.config import ML_ACCESS_TOKEN, ML_SELLER_ID
from core.http_client import request
from core.marketplace_keepalive import registrar_acesso, dias_sem_acesso
from core.token_manager import get_token_ml

logger = logging.getLogger("ml_client")
BASE = "https://api.mercadolibre.com"


def _enabled() -> bool:
    return bool(ML_ACCESS_TOKEN and ML_SELLER_ID)


def _h():
    # Prefere token renovado automaticamente; fallback para token estático do .env.
    token = get_token_ml() or ML_ACCESS_TOKEN
    return {"Authorization": f"Bearer {token}"}


def listar_perguntas_nao_respondidas() -> list[dict]:
    if not _enabled():
        logger.warning("Mercado Livre não configurado.")
        return []
    try:
        r = request(
            "GET",
            f"{BASE}/my/received_questions/search",
            headers=_h(),
            params={"status": "UNANSWERED", "seller_id": ML_SELLER_ID},
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("questions", [])
    except Exception as exc:
        logger.error("ML listar_perguntas_nao_respondidas erro: %s", exc)
        return []


def responder_pergunta(question_id: str, texto: str) -> bool:
    if not _enabled():
        logger.warning("Mercado Livre não configurado para responder pergunta.")
        return False
    try:
        r = request(
            "POST",
            f"{BASE}/answers",
            headers=_h(),
            json={"question_id": question_id, "text": texto},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.error("ML responder_pergunta erro question_id=%s: %s", question_id, exc)
        return False


def buscar_reputacao_vendedor() -> dict:
    if not _enabled():
        logger.warning("Mercado Livre não configurado para reputação.")
        return {}
    try:
        r = request("GET", f"{BASE}/users/{ML_SELLER_ID}", headers=_h(), timeout=20)
        r.raise_for_status()
        return r.json().get("seller_reputation", {})
    except Exception as exc:
        logger.error("ML buscar_reputacao_vendedor erro: %s", exc)
        return {}


def obter_saude_conta() -> dict:
    configurado = _enabled()
    if not configurado:
        return {"configurado": False, "pendencias": 0, "claims_rate": 0.0, "dias_sem_acesso": 999}

    perguntas = listar_perguntas_nao_respondidas()
    reputacao = buscar_reputacao_vendedor()
    registrar_acesso("mercadolivre")
    claims_rate = reputacao.get("metrics", {}).get("claims", {}).get("rate", 0) or 0

    return {
        "configurado": True,
        "pendencias": len(perguntas),
        "claims_rate": float(claims_rate),
        "dias_sem_acesso": dias_sem_acesso("mercadolivre") or 0,
    }


def atualizar_preco_item(item_id: str, novo_preco: float) -> bool:
    if not _enabled():
        logger.warning("Mercado Livre não configurado para atualização de preço.")
        return False
    try:
        r = request(
            "PUT",
            f"{BASE}/items/{item_id}",
            headers=_h(),
            json={"price": float(novo_preco)},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.error("ML atualizar_preco_item erro item_id=%s: %s", item_id, exc)
        return False


def atualizar_estoque_item(item_id: str, novo_estoque: int) -> bool:
    if not _enabled():
        logger.warning("Mercado Livre não configurado para atualização de estoque.")
        return False
    try:
        r = request(
            "PUT",
            f"{BASE}/items/{item_id}",
            headers=_h(),
            json={"available_quantity": int(max(0, novo_estoque))},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.error("ML atualizar_estoque_item erro item_id=%s: %s", item_id, exc)
        return False
