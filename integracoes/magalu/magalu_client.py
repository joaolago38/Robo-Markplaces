"""
integracoes/magalu/magalu_client.py
Cliente Magalu OpenAPI (developers.magalu.com) — Produtos, Pedidos e
Perguntas & Respostas.

IMPORTANTE: a autenticação é só `Authorization: Bearer <access_token>`.
Não existe header de "seller id" — o token OAuth por si só já
identifica o seller (fluxo Authorization Code, um consentimento por
seller). Ver:
https://developers.magalu.com/docs/first-steps/create-an-application/authentication-authorization
"""
import logging
from datetime import datetime, timedelta, timezone

from core.config import MAGALU_ACCESS_TOKEN, MAGALU_CHANNEL_ID, MAGALU_REFRESH_TOKEN
from core.datadog_metrics import incrementar
from core.http_client import request
from core.http_errors import log_http_erro_listagem, status_http
from core.marketplace_keepalive import dias_sem_acesso, registrar_acesso
from core.token_manager import get_token_magalu

logger = logging.getLogger("magalu_client")
BASE = "https://api.magalu.com"
# Endpoints com escopo "services:*" (Perguntas & Respostas, Tickets,
# Conversations) vivem em um host separado dos endpoints "open:*"
# (Produtos, Pedidos). Confirmado manualmente em 01/07/2026: GET
# https://services.magalu.com/v0/questions retornou 200, enquanto
# https://api.magalu.com/v0/questions retorna 404 resource_not_found.
BASE_SERVICES = "https://services.magalu.com"
# Reservado para channel.id em endpoints de portfólio (quando confirmados na doc).
_MAGALU_CHANNEL_ID = MAGALU_CHANNEL_ID


def _enabled() -> bool:
    return bool(MAGALU_ACCESS_TOKEN or MAGALU_REFRESH_TOKEN)


def _h():
    tok = MAGALU_ACCESS_TOKEN
    if MAGALU_REFRESH_TOKEN:
        tok = get_token_magalu() or MAGALU_ACCESS_TOKEN
    return {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    }


def probe_conexao() -> dict:
    """Diagnóstico sem mascarar erros HTTP como lista vazia."""
    if not _enabled():
        return {"ok": False, "status": 0, "msg": "Magalu não configurado"}
    try:
        r = request(
            "GET",
            f"{BASE_SERVICES}/v0/questions",
            headers=_h(),
            params={"limit": 1},
            timeout=15,
        )
        status = getattr(r, "status_code", 0)
        if status == 200:
            return {"ok": True, "status": 200, "msg": "autenticado"}
        if status == 401:
            return {"ok": False, "status": 401, "msg": "token expirado ou inválido"}
        if status == 403:
            return {
                "ok": False,
                "status": 403,
                "msg": "sem permissão — verifique escopos OAuth do app Magalu",
            }
        return {"ok": False, "status": status, "msg": (getattr(r, "text", "") or "")[:200]}
    except Exception as exc:
        logger.error("Magalu probe_conexao erro: %s", exc)
        return {"ok": False, "status": 0, "msg": str(exc)}


def _listar_perguntas_nao_respondidas_detalhado(limit: int = 20, max_paginas: int = 5) -> tuple[list[dict], bool]:
    """Retorna (perguntas, sucesso_chamada), percorrendo páginas via offset."""
    if not _enabled():
        logger.warning("Magalu não configurado.")
        return [], False
    out: list[dict] = []
    offset = 0
    try:
        for _pagina in range(max(1, max_paginas)):
            r = request(
                "GET",
                f"{BASE_SERVICES}/v0/questions",
                headers=_h(),
                params={"status": "pending", "limit": limit, "offset": offset},
                timeout=20,
            )
            if status_http(r) != 200:
                log_http_erro_listagem(logger, "Magalu listar_perguntas_nao_respondidas", r)
                return out, False
            body = r.json()
            pagina = body.get("data", body.get("items", []))
            if not isinstance(pagina, list):
                pagina = []
            out.extend(pagina)
            if len(pagina) < limit:
                break
            offset += limit
        return out, True
    except Exception as exc:
        incrementar("dados.degradado", tags=["contexto:Magalu_listar_perguntas_nao_respondidas", "motivo:excecao"])
        logger.error("Magalu listar_perguntas_nao_respondidas erro: %s", exc)
        return out, False


def listar_perguntas_nao_respondidas(limit: int = 20) -> list[dict]:
    perguntas, _ok = _listar_perguntas_nao_respondidas_detalhado(limit=limit)
    return perguntas


def responder_pergunta(question_id: str, texto: str) -> bool:
    if not _enabled():
        logger.warning("Magalu não configurado para responder pergunta.")
        return False
    try:
        r = request(
            "POST",
            f"{BASE_SERVICES}/v0/questions/{question_id}/answer",
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
            f"{BASE_SERVICES}/v0/questions",
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

    perguntas, ok = _listar_perguntas_nao_respondidas_detalhado(limit=50)
    if ok:
        registrar_acesso("magalu")

    return {
        "configurado": True,
        "api_ok": ok,
        "pendencias": len(perguntas),
        "claims_rate": 0.0,
        "dias_sem_acesso": dias_sem_acesso("magalu") or 0,
    }


def atualizar_preco_item(sku: str, novo_preco: float) -> bool:
    from core.guardrails import bloqueio_escrita_global

    if bloqueio := bloqueio_escrita_global():
        logger.warning("Magalu atualizar_preco_item bloqueado: %s", bloqueio["erro"])
        return False
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
    from core.guardrails import bloqueio_escrita_global

    if bloqueio := bloqueio_escrita_global():
        logger.warning("Magalu atualizar_estoque_item bloqueado: %s", bloqueio["erro"])
        return False
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


def listar_pedidos_detalhado(dias: int = 7, *, max_paginas: int = 10) -> tuple[list[dict], bool]:
    """
    Lista pedidos recentes via GET /seller/v1/orders, percorrendo páginas
    via offset até esgotar ou atingir max_paginas.
    Retorna (pedidos, sucesso_chamada) — use isto quando precisar saber se
    a lista vazia é "sem venda nova" ou "a chamada falhou de verdade".
    Retorno alinhado ao padrão do ML.
    """
    if not _enabled():
        logger.warning("Magalu não configurado para listar pedidos.")
        return [], False

    out: list[dict] = []
    limite_data = datetime.now(timezone.utc) - timedelta(days=max(1, int(dias)))
    limit = 50
    offset = 0
    try:
        for _pagina in range(max(1, max_paginas)):
            r = request(
                "GET",
                f"{BASE}/seller/v1/orders",
                headers=_h(),
                params={"limit": limit, "offset": offset},
                timeout=25,
            )
            if status_http(r) != 200:
                log_http_erro_listagem(logger, "Magalu listar_pedidos", r)
                return out, False
            body = r.json() or {}
            rows = body.get("data") or body.get("items") or body.get("orders") or []
            if not isinstance(rows, list):
                return out, False

            pagina_chegou_no_limite_de_data = False
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
                        if created < limite_data:
                            # Lista vem ordenada do mais recente pro mais antigo;
                            # ao achar o primeiro pedido fora da janela, as
                            # próximas páginas só teriam pedidos ainda mais
                            # antigos — para de paginar (não é falha).
                            pagina_chegou_no_limite_de_data = True
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

                status_raw = row.get("status")
                out.append(
                    {
                        "order_id": oid,
                        # Sem assumir "paid" quando a API não manda status —
                        # um valor ausente/nulo não pode virar "pago" por padrão.
                        "status": str(status_raw).lower() if status_raw else "desconhecido",
                        "total": total,
                        "data": str(created_raw or ""),
                        "itens": itens,
                    }
                )

            if pagina_chegou_no_limite_de_data or len(rows) < limit:
                break
            offset += limit
        else:
            logger.warning(
                "Magalu listar_pedidos: atingiu max_paginas=%s sem esgotar resultados "
                "(offset=%s) — pode haver pedidos não coletados.",
                max_paginas,
                offset,
            )
            incrementar("dados.degradado", tags=["contexto:Magalu_listar_pedidos", "motivo:paginacao_truncada"])
            return out, False

        return out, True
    except Exception as exc:
        incrementar("dados.degradado", tags=["contexto:Magalu_listar_pedidos", "motivo:excecao"])
        logger.error("Magalu listar_pedidos erro: %s", exc)
        return out, False


def listar_pedidos(dias: int = 7) -> list[dict]:
    pedidos, _ok = listar_pedidos_detalhado(dias)
    return pedidos
