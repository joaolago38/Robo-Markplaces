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
    SHOPEE_REFRESH_TOKEN,
    SHOPEE_SHOP_ID,
)
from core.http_client import request
from core.token_manager import get_token_shopee
from core.marketplace_keepalive import registrar_acesso, dias_sem_acesso

logger = logging.getLogger("shopee_client")
BASE = "https://partner.shopeemobile.com"


def _enabled() -> bool:
    tem_token = bool(SHOPEE_ACCESS_TOKEN or SHOPEE_REFRESH_TOKEN)
    return bool(SHOPEE_PARTNER_ID and SHOPEE_PARTNER_KEY and SHOPEE_SHOP_ID and tem_token)


def _token_para_assinatura() -> str:
    if SHOPEE_REFRESH_TOKEN:
        return get_token_shopee() or SHOPEE_ACCESS_TOKEN or ""
    return SHOPEE_ACCESS_TOKEN or ""


def _assinar(path: str, timestamp: int) -> str:
    tok = _token_para_assinatura()
    base = f"{SHOPEE_PARTNER_ID}{path}{timestamp}{tok}{SHOPEE_SHOP_ID}"
    return hmac.new(SHOPEE_PARTNER_KEY.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()


def _params(path: str) -> dict:
    ts = int(time.time())
    tok = _token_para_assinatura()
    return {
        "partner_id": int(SHOPEE_PARTNER_ID),
        "timestamp": ts,
        "access_token": tok,
        "shop_id": int(SHOPEE_SHOP_ID),
        "sign": _assinar(path, ts),
    }


def _tem_erro_api(body: dict) -> bool:
    error = body.get("error")
    if error not in (None, "", 0):
        return True

    response = body.get("response", {})
    if not isinstance(response, dict):
        return False

    response_error = response.get("error")
    if response_error not in (None, "", 0):
        return True

    for key in ("errors", "error_list", "failed_list"):
        value = response.get(key)
        if isinstance(value, list) and value:
            return True

    return False


def _listar_perguntas_nao_respondidas_detalhado(page_size: int = 20, max_pages: int = 3) -> tuple[list[dict], bool]:
    """
    Endpoint pode variar entre contas; retorna (lista, sucesso_chamada).
    """
    if not _enabled():
        logger.warning("Shopee não configurado.")
        return [], False
    path = "/api/v2/product/get_comment"
    comentarios: list[dict] = []
    cursor: str | None = None
    page = 0

    try:
        while page < max(1, int(max_pages)):
            params = {
                **_params(path),
                "page_size": max(1, min(100, int(page_size))),
                "comment_status": "UNREAD",
            }
            if cursor:
                params["cursor"] = cursor

            r = request(
                "GET",
                f"{BASE}{path}",
                params=params,
                timeout=20,
            )
            r.raise_for_status()
            body = r.json()
            if _tem_erro_api(body):
                logger.error("Shopee listar_perguntas_nao_respondidas erro de API: %s", body.get("error"))
                return comentarios, False

            data = body.get("response", {})
            page_comments = data.get("comment_list", [])
            if isinstance(page_comments, list):
                comentarios.extend(page_comments)

            cursor = data.get("next_cursor")
            has_next = bool(data.get("more") or data.get("has_next_page") or cursor)
            page += 1
            if not has_next:
                break

        return comentarios, True
    except Exception as exc:
        logger.error("Shopee listar_perguntas_nao_respondidas erro: %s", exc)
        return comentarios, False


def listar_perguntas_nao_respondidas(page_size: int = 20, max_pages: int = 3) -> list[dict]:
    perguntas, _ok = _listar_perguntas_nao_respondidas_detalhado(page_size=page_size, max_pages=max_pages)
    return perguntas


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
        return not _tem_erro_api(body)
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
            body = r.json()
            if _tem_erro_api(body):
                logger.error("Shopee manter_conta_ativa erro de API: %s", body.get("error"))
                sem_acesso_atual = dias_sem_acesso("shopee")
                return {
                    "ok": False,
                    "marketplace": "shopee",
                    "acao": "falha no keepalive",
                    "dias_sem_acesso": sem_acesso_atual if sem_acesso_atual is not None else -1,
                    "alerta": True,
                }
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

    pendencias, ok = _listar_perguntas_nao_respondidas_detalhado(page_size=50, max_pages=4)
    if ok:
        registrar_acesso("shopee")

    return {
        "configurado": True,
        "pendencias": len(pendencias),
        "claims_rate": 0.0,
        "dias_sem_acesso": dias_sem_acesso("shopee") or 0,
    }


def atualizar_preco_item(item_id: int, novo_preco: float, model_id: int | None = None) -> bool:
    if not _enabled():
        logger.warning("Shopee não configurado para atualização de preço.")
        return False
    path = "/api/v2/product/update_price"
    try:
        item_payload = {"item_id": int(item_id), "original_price": float(novo_preco)}
        if model_id is not None:
            item_payload["model_list"] = [{"model_id": int(model_id), "original_price": float(novo_preco)}]
        payload = {"price_list": [item_payload]}
        r = request(
            "POST",
            f"{BASE}{path}",
            params=_params(path),
            json=payload,
            timeout=20,
        )
        r.raise_for_status()
        body = r.json()
        return not _tem_erro_api(body)
    except Exception as exc:
        logger.error("Shopee atualizar_preco_item erro item_id=%s: %s", item_id, exc)
        return False


def atualizar_estoque_item(item_id: int, novo_estoque: int, model_id: int | None = None) -> bool:
    if not _enabled():
        logger.warning("Shopee não configurado para atualização de estoque.")
        return False
    path = "/api/v2/product/update_stock"
    try:
        item_payload = {"item_id": int(item_id), "normal_stock": int(max(0, novo_estoque))}
        if model_id is not None:
            item_payload["model_list"] = [{"model_id": int(model_id), "normal_stock": int(max(0, novo_estoque))}]
        payload = {"stock_list": [item_payload]}
        r = request(
            "POST",
            f"{BASE}{path}",
            params=_params(path),
            json=payload,
            timeout=20,
        )
        r.raise_for_status()
        body = r.json()
        return not _tem_erro_api(body)
    except Exception as exc:
        logger.error("Shopee atualizar_estoque_item erro item_id=%s: %s", item_id, exc)
        return False
