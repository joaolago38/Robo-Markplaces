"""
integracoes/amazon/amazon_client.py
Cliente básico da Amazon SP-API para mensagens de comprador.
"""
import logging
from datetime import datetime, timedelta, timezone

from core.config import AMAZON_ACCESS_TOKEN, AMAZON_MARKETPLACE_ID
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


def atualizar_preco_item(sku: str, novo_preco: float) -> bool:
    if not _enabled():
        logger.warning("Amazon não configurado para atualização de preço.")
        return False
    try:
        r = request(
            "PATCH",
            f"{BASE}/listings/2021-08-01/items/{sku}",
            headers=_h(),
            json={"attributes": {"purchasable_offer": [{"our_price": [{"schedule": [{"value_with_tax": float(novo_preco)}]}]}]}},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Amazon atualizar_preco_item erro sku=%s: %s", sku, exc)
        return False


def listar_pedidos(dias: int = 7) -> list[dict]:
    """
    Lista pedidos recentes (Orders API v0).
    Retorno alinhado ao padrão do ML. Nunca lança exceção.
    """
    if not _enabled():
        logger.warning("Amazon não configurada para listar pedidos.")
        return []
    try:
        ts = datetime.now(timezone.utc) - timedelta(days=max(1, int(dias)))
        created_after = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        r = request(
            "GET",
            f"{BASE}/orders/v0/orders",
            headers=_h(),
            params={
                "MarketplaceIds": AMAZON_MARKETPLACE_ID,
                "CreatedAfter": created_after,
                "MaxResultsPerPage": 30,
            },
            timeout=25,
        )
        r.raise_for_status()
        data = r.json() or {}
        payload = data.get("payload") or {}
        orders = payload.get("Orders") or payload.get("orders") or []
        if not isinstance(orders, list):
            return []

        out: list[dict] = []
        for o in orders[:25]:
            if not isinstance(o, dict):
                continue
            oid = str(o.get("AmazonOrderId", "") or "")
            if not oid:
                continue
            ot = o.get("OrderTotal") or {}
            try:
                total = float(ot.get("Amount", 0) or 0)
            except (TypeError, ValueError):
                total = 0.0
            purchase = str(o.get("PurchaseDate", "") or "")

            itens: list[dict] = []
            try:
                ri = request(
                    "GET",
                    f"{BASE}/orders/v0/orders/{oid}/orderItems",
                    headers=_h(),
                    timeout=25,
                )
                ri.raise_for_status()
                pdata = ri.json().get("payload") or {}
                raw_items = pdata.get("OrderItems") or pdata.get("orderItems") or []
                if isinstance(raw_items, list):
                    for it in raw_items:
                        if not isinstance(it, dict):
                            continue
                        try:
                            qty = int(it.get("QuantityOrdered", 1) or 1)
                        except (TypeError, ValueError):
                            qty = 1
                        ip = it.get("ItemPrice") or {}
                        try:
                            pu = float(ip.get("Amount", 0) or 0)
                        except (TypeError, ValueError):
                            pu = 0.0
                        sku = str(it.get("SellerSKU", "") or it.get("ASIN", "") or "")
                        itens.append(
                            {
                                "sku": sku,
                                "item_id": str(it.get("ASIN", "") or ""),
                                "quantidade": qty,
                                "preco_unitario": pu,
                            }
                        )
            except Exception as exc:
                logger.warning("Amazon orderItems order=%s: %s", oid, exc)

            out.append(
                {
                    "order_id": oid,
                    "status": str(o.get("OrderStatus", "paid") or "").lower(),
                    "total": total,
                    "data": purchase,
                    "itens": itens,
                }
            )
        return out
    except Exception as exc:
        logger.error("Amazon listar_pedidos erro: %s", exc)
        return []
