"""
integracoes/magalu/magalu_client.py
Cliente Magalu Seller API para perguntas e respostas.
"""
import logging
from datetime import datetime, timedelta, timezone

from core.config import MAGALU_ACCESS_TOKEN, MAGALU_MERCHANT_ID, MAGALU_REFRESH_TOKEN
from core.http_client import request
from core.token_manager import get_token_magalu
from core.marketplace_keepalive import registrar_acesso, dias_sem_acesso

logger = logging.getLogger("magalu_client")
BASE = "https://api.magalu.com"


def _enabled() -> bool:
    tem_token = bool(MAGALU_ACCESS_TOKEN or MAGALU_REFRESH_TOKEN)
    return bool(tem_token and MAGALU_MERCHANT_ID)


def _h():
    tok = MAGALU_ACCESS_TOKEN
    if MAGALU_REFRESH_TOKEN:
        tok = get_token_magalu() or MAGALU_ACCESS_TOKEN
    return {
        "Authorization": f"Bearer {tok}",
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


def atualizar_preco_item(sku: str, novo_preco: float) -> bool:
    if not _enabled():
        logger.warning("Magalu não configurado para atualização de preço.")
        return False
    try:
        r = request(
            "PUT",
            f"{BASE}/seller/products/{sku}/price",
            headers=_h(),
            json={"price": float(novo_preco)},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Magalu atualizar_preco_item erro sku=%s: %s", sku, exc)
        return False


def atualizar_estoque_item(sku: str, novo_estoque: int) -> bool:
    if not _enabled():
        logger.warning("Magalu não configurado para atualização de estoque.")
        return False
    try:
        r = request(
            "PUT",
            f"{BASE}/seller/products/{sku}/stock",
            headers=_h(),
            json={"quantity": int(max(0, novo_estoque))},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Magalu atualizar_estoque_item erro sku=%s: %s", sku, exc)
        return False


def listar_pedidos(dias: int = 7) -> list[dict]:
    """
    Lista pedidos recentes via GET /seller/v1/orders.
    Retorno alinhado ao padrão do ML. Nunca lança exceção.
    """
    if not _enabled():
        logger.warning("Magalu não configurado para listar pedidos.")
        return []
    try:
        r = request(
            "GET",
            f"{BASE}/seller/v1/orders",
            headers=_h(),
            params={"limit": 50},
            timeout=25,
        )
        if r.status_code == 404:
            logger.warning("Magalu listar_pedidos: endpoint não encontrado (404).")
            return []
        r.raise_for_status()
        body = r.json() or {}
        rows = body.get("data") or body.get("items") or body.get("orders") or []
        if not isinstance(rows, list):
            return []

        limite = datetime.now(timezone.utc) - timedelta(days=max(1, int(dias)))
        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            oid = str(row.get("code") or row.get("id") or row.get("order_id") or "")
            if not oid:
                continue
            created_raw = (
                row.get("created_at")
                or row.get("createdAt")
                or row.get("inserted_at")
                or row.get("ordered_at")
            )
            if created_raw:
                try:
                    created = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if created < limite:
                        continue
                except (TypeError, ValueError):
                    pass

            items_src = row.get("items") or row.get("products") or row.get("order_items") or []
            itens: list[dict] = []
            if isinstance(items_src, list):
                for it in items_src:
                    if not isinstance(it, dict):
                        continue
                    try:
                        qty = int(it.get("quantity") or it.get("qty") or 1)
                    except (TypeError, ValueError):
                        qty = 1
                    try:
                        pu = float(it.get("price") or it.get("unit_price") or 0)
                    except (TypeError, ValueError):
                        pu = 0.0
                    itens.append(
                        {
                            "sku": str(it.get("sku") or it.get("id") or it.get("product_id") or ""),
                            "item_id": str(it.get("id") or it.get("product_id") or ""),
                            "quantidade": qty,
                            "preco_unitario": pu,
                        }
                    )
            try:
                total = float(row.get("total") or row.get("amount") or row.get("total_price") or 0)
            except (TypeError, ValueError):
                total = 0.0

            out.append(
                {
                    "order_id": oid,
                    "status": str(row.get("status", "paid") or "paid").lower(),
                    "total": total,
                    "data": str(created_raw or ""),
                    "itens": itens,
                }
            )
        return out
    except Exception as exc:
        logger.error("Magalu listar_pedidos erro: %s", exc)
        return []
