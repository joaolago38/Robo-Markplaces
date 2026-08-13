"""
integracoes/amazon/amazon_client.py
Cliente básico da Amazon SP-API para mensagens de comprador.
"""
import logging
from datetime import datetime, timedelta, timezone

from core.config import (
    AMAZON_ACCESS_TOKEN,
    AMAZON_LWA_CLIENT_ID,
    AMAZON_LWA_CLIENT_SECRET,
    AMAZON_MARKETPLACE_ID,
    AMAZON_REFRESH_TOKEN,
    AMAZON_SELLER_ID,
)
from core.datadog_metrics import incrementar
from core.http_client import request
from core.http_errors import log_http_erro_listagem, status_http
from core.marketplace_keepalive import dias_sem_acesso, registrar_acesso
from core.token_manager import get_token_amazon

logger = logging.getLogger("amazon_client")
BASE = "https://sellingpartnerapi-na.amazon.com"


def _enabled() -> bool:
    tem_refresh = bool(
        AMAZON_LWA_CLIENT_ID and AMAZON_LWA_CLIENT_SECRET and AMAZON_REFRESH_TOKEN
    )
    return bool(AMAZON_ACCESS_TOKEN or tem_refresh)


def _h():
    tok = get_token_amazon() or AMAZON_ACCESS_TOKEN or ""
    return {
        "x-amz-access-token": tok,
        "Content-Type": "application/json",
    }


def probe_conexao() -> dict:
    if not _enabled():
        return {"ok": False, "status": 0, "msg": "Amazon não configurado"}
    try:
        r = request(
            "GET",
            f"{BASE}/messaging/v1/customerMessages",
            headers=_h(),
            params={"pageSize": 1},
            timeout=15,
        )
        status = getattr(r, "status_code", 0)
        if status == 200:
            return {"ok": True, "status": 200, "msg": "autenticado"}
        if status == 401:
            return {"ok": False, "status": 401, "msg": "token expirado ou inválido"}
        if status == 403:
            return {"ok": False, "status": 403, "msg": "sem permissão — verifique escopos SP-API"}
        return {"ok": False, "status": status, "msg": (getattr(r, "text", "") or "")[:200]}
    except Exception as exc:
        logger.error("Amazon probe_conexao erro: %s", exc)
        return {"ok": False, "status": 0, "msg": str(exc)}


def listar_mensagens_nao_respondidas_detalhado(limit: int = 20) -> tuple[list[dict], bool]:
    if not _enabled():
        logger.info("Amazon não configurado.")
        return [], False
    try:
        r = request(
            "GET",
            f"{BASE}/messaging/v1/customerMessages",
            headers=_h(),
            params={"status": "UNREAD", "pageSize": limit},
            timeout=20,
        )
        if status_http(r) != 200:
            log_http_erro_listagem(logger, "Amazon listar_mensagens_nao_respondidas", r)
            return [], False
        return r.json().get("messages", []), True
    except Exception as exc:
        incrementar("dados.degradado", tags=["contexto:Amazon_listar_mensagens", "motivo:excecao"])
        logger.error("Amazon listar_mensagens_nao_respondidas erro: %s", exc)
        return [], False


def listar_mensagens_nao_respondidas(limit: int = 20) -> list[dict]:
    mensagens, _ok = listar_mensagens_nao_respondidas_detalhado(limit=limit)
    return mensagens


def responder_mensagem(thread_id: str, texto: str) -> bool:
    if not _enabled():
        logger.info("Amazon não configurado para responder mensagem.")
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
        return {
            "configurado": False,
            "pendencias": 0,
            "claims_rate": None,
            "claims_conhecido": False,
            "dias_sem_acesso": 999,
            "conta_id": str(AMAZON_SELLER_ID or "").strip(),
            "estoque_sync": False,
        }

    mensagens, ok = listar_mensagens_nao_respondidas_detalhado(limit=50)
    if ok:
        registrar_acesso("amazon")
    return {
        "configurado": True,
        "api_ok": ok,
        "pendencias": len(mensagens),
        "claims_rate": None,
        "claims_conhecido": False,
        "dias_sem_acesso": dias_sem_acesso("amazon") or 0,
        "conta_id": str(AMAZON_SELLER_ID or "").strip(),
        "estoque_sync": False,
        "modelo": "buybox_amazon",
    }


def atualizar_preco_item(sku: str, novo_preco: float) -> bool:
    from core.guardrails import bloqueio_escrita_global

    if bloqueio := bloqueio_escrita_global():
        logger.warning("Amazon atualizar_preco_item bloqueado: %s", bloqueio["erro"])
        return False
    if not _enabled():
        logger.info("Amazon não configurado para atualização de preço.")
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


def listar_pedidos_detalhado(dias: int = 7, *, max_paginas: int = 10) -> tuple[list[dict], bool]:
    """
    Lista pedidos recentes (Orders API v0).
    Retorna (pedidos, sucesso_chamada). Retorno alinhado ao padrão do ML.
    Nunca lança exceção.
    """
    if not _enabled():
        logger.info("Amazon não configurada para listar pedidos.")
        return [], False
    out: list[dict] = []
    try:
        ts = datetime.now(timezone.utc) - timedelta(days=max(1, int(dias)))
        created_after = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        next_token: str | None = None

        for _pagina in range(max(1, max_paginas)):
            params: dict = {
                "MarketplaceIds": AMAZON_MARKETPLACE_ID,
                "CreatedAfter": created_after,
                "MaxResultsPerPage": 30,
            }
            if next_token:
                params["NextToken"] = next_token
            r = request(
                "GET",
                f"{BASE}/orders/v0/orders",
                headers=_h(),
                params=params,
                timeout=25,
            )
            if status_http(r) != 200:
                log_http_erro_listagem(logger, "Amazon listar_pedidos", r)
                return out, False
            data = r.json() or {}
            payload = data.get("payload") or {}
            orders = payload.get("Orders") or payload.get("orders") or []
            if not isinstance(orders, list):
                return out, False

            for o in orders:
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

            next_token = payload.get("NextToken")
            if not next_token:
                break
        else:
            incrementar("dados.degradado", tags=["contexto:Amazon_listar_pedidos", "motivo:paginacao_truncada"])
            return out, False

        return out, True
    except Exception as exc:
        incrementar("dados.degradado", tags=["contexto:Amazon_listar_pedidos", "motivo:excecao"])
        logger.error("Amazon listar_pedidos erro: %s", exc)
        return out, False


def listar_pedidos(dias: int = 7) -> list[dict]:
    pedidos, _ok = listar_pedidos_detalhado(dias)
    return pedidos
