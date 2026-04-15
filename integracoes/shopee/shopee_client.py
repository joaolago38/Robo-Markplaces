"""
integracoes/shopee/shopee_client.py
Cliente Shopee para leitura de perguntas e envio de resposta.
"""
import hashlib
import hmac
import logging
import time

from core.config import (
    SHOPEE_ACCESS_TOKEN,
    SHOPEE_PARTNER_ID,
    SHOPEE_PARTNER_KEY,
    SHOPEE_SHOP_ID,
)
from core.http_client import request
from core.marketplace_keepalive import registrar_acesso, dias_sem_acesso

logger = logging.getLogger("shopee_client")
BASE = "https://partner.shopeemobile.com"


def _enabled() -> bool:
    return bool(SHOPEE_PARTNER_ID and SHOPEE_PARTNER_KEY and SHOPEE_SHOP_ID and SHOPEE_ACCESS_TOKEN)


def _assinar(path: str, timestamp: int) -> str:
    base = f"{SHOPEE_PARTNER_ID}{path}{timestamp}{SHOPEE_ACCESS_TOKEN}{SHOPEE_SHOP_ID}"
    return hmac.new(SHOPEE_PARTNER_KEY.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()


def _params(path: str) -> dict:
    ts = int(time.time())
    return {
        "partner_id": int(SHOPEE_PARTNER_ID),
        "timestamp": ts,
        "access_token": SHOPEE_ACCESS_TOKEN,
        "shop_id": int(SHOPEE_SHOP_ID),
        "sign": _assinar(path, ts),
    }


def listar_perguntas_nao_respondidas(page_size: int = 20) -> list[dict]:
    """
    Endpoint pode variar entre contas; falha retorna lista vazia.
    """
    if not _enabled():
        logger.warning("Shopee não configurado.")
        return []
    path = "/api/v2/product/get_comment"
    try:
        r = request(
            "GET",
            f"{BASE}{path}",
            params={**_params(path), "page_size": page_size},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json().get("response", {})
        return data.get("comment_list", [])
    except Exception as exc:
        logger.error("Shopee listar_perguntas_nao_respondidas erro: %s", exc)
        return []


def responder_pergunta(item_id: int, comment_id: int, texto: str) -> bool:
    """
    Endpoint de reply pode variar por categoria/permissão.
    """
    if not _enabled():
        logger.warning("Shopee não configurado para responder pergunta.")
        return False
    path = "/api/v2/product/reply_comment"
    try:
        payload = {"item_id": int(item_id), "comment_id": int(comment_id), "comment": texto}
        r = request(
            "POST",
            f"{BASE}{path}",
            params=_params(path),
            json=payload,
            timeout=20,
        )
        r.raise_for_status()
        body = r.json()
        return body.get("error") in (None, "", 0)
    except Exception as exc:
        logger.error("Shopee responder_pergunta erro item=%s comment=%s: %s", item_id, comment_id, exc)
        return False


def manter_conta_ativa(limite_dias_sem_acesso: int = 5) -> dict:
    """
    Faz uma chamada leve na API para manter histórico de acesso.
    """
    sem_acesso = dias_sem_acesso("shopee")
    if sem_acesso is not None and sem_acesso < 1:
        return {"ok": True, "marketplace": "shopee", "acao": "já acessado hoje", "dias_sem_acesso": sem_acesso}

    if _enabled():
        path = "/api/v2/product/get_comment"
        try:
            r = request(
                "GET",
                f"{BASE}{path}",
                params={**_params(path), "page_size": 1},
                timeout=20,
            )
            r.raise_for_status()
            registrar_acesso("shopee")
            sem_acesso_atual = dias_sem_acesso("shopee") or 0
            return {
                "ok": True,
                "marketplace": "shopee",
                "acao": "keepalive executado",
                "dias_sem_acesso": sem_acesso_atual,
                "alerta": sem_acesso_atual >= limite_dias_sem_acesso,
            }
        except Exception as exc:
            logger.error("Shopee manter_conta_ativa erro: %s", exc)
            sem_acesso_atual = dias_sem_acesso("shopee")
            return {
                "ok": False,
                "marketplace": "shopee",
                "acao": "falha no keepalive",
                "dias_sem_acesso": sem_acesso_atual if sem_acesso_atual is not None else -1,
                "alerta": True,
            }

    return {
        "ok": False,
        "marketplace": "shopee",
        "acao": "não configurado",
        "dias_sem_acesso": sem_acesso if sem_acesso is not None else -1,
        "alerta": True,
    }


def obter_saude_conta() -> dict:
    if not _enabled():
        return {"configurado": False, "pendencias": 0, "claims_rate": 0.0, "dias_sem_acesso": 999}

    pendencias = listar_perguntas_nao_respondidas(page_size=50)
    registrar_acesso("shopee")

    return {
        "configurado": True,
        "pendencias": len(pendencias),
        "claims_rate": 0.0,
        "dias_sem_acesso": dias_sem_acesso("shopee") or 0,
    }


def atualizar_preco_item(item_id: int, novo_preco: float) -> bool:
    if not _enabled():
        logger.warning("Shopee não configurado para atualização de preço.")
        return False
    path = "/api/v2/product/update_price"
    try:
        payload = {"price_list": [{"item_id": int(item_id), "original_price": float(novo_preco)}]}
        r = request(
            "POST",
            f"{BASE}{path}",
            params=_params(path),
            json=payload,
            timeout=20,
        )
        r.raise_for_status()
        body = r.json()
        return body.get("error") in (None, "", 0)
    except Exception as exc:
        logger.error("Shopee atualizar_preco_item erro item_id=%s: %s", item_id, exc)
        return False


def atualizar_estoque_item(item_id: int, novo_estoque: int) -> bool:
    if not _enabled():
        logger.warning("Shopee não configurado para atualização de estoque.")
        return False
    path = "/api/v2/product/update_stock"
    try:
        payload = {"stock_list": [{"item_id": int(item_id), "normal_stock": int(max(0, novo_estoque))}]}
        r = request(
            "POST",
            f"{BASE}{path}",
            params=_params(path),
            json=payload,
            timeout=20,
        )
        r.raise_for_status()
        body = r.json()
        return body.get("error") in (None, "", 0)
    except Exception as exc:
        logger.error("Shopee atualizar_estoque_item erro item_id=%s: %s", item_id, exc)
        return False
