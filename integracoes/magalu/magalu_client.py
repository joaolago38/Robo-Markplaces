"""
integracoes/magalu/magalu_client.py
Cliente Magalu OpenAPI (developers.magalu.com) — Produtos, Pedidos e
Perguntas & Respostas.

IMPORTANTE: Bearer no `Authorization` identifica o seller. Pedidos
(`/seller/v1/orders`) também exigem `X-Tenant-Id` — senão a API
responde 422 (`Field required`). O tenant vem do claim JWT `tenant`
(fallback: MAGALU_CHANNEL_ID). Não confundir com seller id / CNPJ.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from core import config as cfg
from core.config import MAGALU_ACCESS_TOKEN, MAGALU_CHANNEL_ID, MAGALU_REFRESH_TOKEN, MAGALU_SELLER_ID
from core.datadog_metrics import incrementar
from core.http_client import request
from core.http_errors import log_http_erro_listagem, status_http
from core.marketplace_keepalive import dias_sem_acesso, registrar_acesso
from core.token_manager import escopos_jwt_magalu, get_token_magalu, tenant_jwt_magalu

logger = logging.getLogger("magalu_client")
BASE = "https://api.magalu.com"
# Última listagem de pedidos — distingue auth quebrada de falha genérica
# (vendas_notificador não deve poluir o P1 vendas.busca_falhou com invalid_grant).
_ULTIMA_LISTAGEM_PEDIDOS: dict = {"auth_quebrada": False, "status": 0}
_AVISO_TENANT = {"feito": False}
_PERGUNTAS_SEM_ESCOPO = {"valor": False, "avisou": False}
ESCOPO_PERGUNTAS_READ = "services:questions-seller:read"
# Endpoints com escopo "services:*" (Perguntas & Respostas, Tickets,
# Conversations) vivem em um host separado dos endpoints "open:*"
# (Produtos, Pedidos). Confirmado manualmente em 01/07/2026: GET
# https://services.magalu.com/v0/questions retornou 200, enquanto
# https://api.magalu.com/v0/questions retorna 404 resource_not_found.
BASE_SERVICES = "https://services.magalu.com"


def _canal_operando() -> bool:
    try:
        from core.marketplace_toggle import canal_em_operacao

        return canal_em_operacao("magalu")
    except Exception:
        return True


def _enabled() -> bool:
    if not (MAGALU_ACCESS_TOKEN or MAGALU_REFRESH_TOKEN):
        return False
    return _canal_operando()


def _valor_tenant(valor: Any) -> str:
    txt = str(valor or "").strip()
    if not txt or txt == "...":
        return ""
    return txt


def _tenant_id(tok: str = "") -> str:
    """X-Tenant-Id: JWT do token da request, senão MAGALU_CHANNEL_ID, senão cfg.

    JWT em `core.config` só entra por último — senão o .env de máquina
    vence o patch dos testes e um CHANNEL_ID explícito.
    """
    for candidato in (tok, MAGALU_ACCESS_TOKEN, getattr(cfg, "MAGALU_ACCESS_TOKEN", "")):
        tenant = tenant_jwt_magalu(str(candidato or ""))
        if tenant:
            cfg.MAGALU_CHANNEL_ID = tenant
            return tenant
    for fonte in (
        MAGALU_CHANNEL_ID,
        getattr(cfg, "MAGALU_CHANNEL_ID", ""),
        getattr(cfg, "MAGALU_MERCHANT_ID", ""),
        os.getenv("MAGALU_CHANNEL_ID"),
        os.getenv("MAGALU_MERCHANT_ID"),
    ):
        local = _valor_tenant(fonte)
        if local:
            return local
    return ""


def _headers_com_token(tok: str) -> dict:
    headers = {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    }
    tenant = _tenant_id(str(tok or ""))
    if tenant:
        headers["X-Tenant-Id"] = tenant
    elif not _AVISO_TENANT["feito"]:
        _AVISO_TENANT["feito"] = True
        logger.warning(
            "Magalu sem X-Tenant-Id — preencha MAGALU_CHANNEL_ID (claim JWT tenant) "
            "ou o GET /seller/v1/orders responde 422"
        )
    return headers


def _h():
    tok = str(getattr(cfg, "MAGALU_ACCESS_TOKEN", "") or MAGALU_ACCESS_TOKEN or "")
    refresh = str(getattr(cfg, "MAGALU_REFRESH_TOKEN", "") or MAGALU_REFRESH_TOKEN or "")
    if refresh:
        tok = get_token_magalu() or tok
    return _headers_com_token(str(tok or ""))


def _request_magalu(method: str, url: str, *, timeout: int = 20, **kwargs: Any):
    """Request autenticado com retry único em 401 (renova e repete uma vez)."""
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update(_h())
    kwargs["headers"] = headers

    r = request(method, url, timeout=timeout, **kwargs)
    if getattr(r, "status_code", 0) != 401:
        return r

    logger.warning("Magalu HTTP 401 — renovando token e repetindo request")
    novo = get_token_magalu(forcar=True)
    if not novo:
        return r
    incrementar("token.recuperacao_automatica", tags=["provider:magalu"])
    kwargs["headers"] = _headers_com_token(str(novo))
    return request(method, url, timeout=timeout, **kwargs)


def _token_atual() -> str:
    tok = str(getattr(cfg, "MAGALU_ACCESS_TOKEN", "") or MAGALU_ACCESS_TOKEN or "")
    refresh = str(getattr(cfg, "MAGALU_REFRESH_TOKEN", "") or MAGALU_REFRESH_TOKEN or "")
    if refresh:
        tok = get_token_magalu() or tok
    return str(tok or "")


def _pode_listar_perguntas() -> bool:
    if _PERGUNTAS_SEM_ESCOPO["valor"]:
        return False
    tok = _token_atual()
    escopos = escopos_jwt_magalu(tok)
    if not escopos:
        return True
    if ESCOPO_PERGUNTAS_READ in escopos:
        return True
    _PERGUNTAS_SEM_ESCOPO["valor"] = True
    if not _PERGUNTAS_SEM_ESCOPO["avisou"]:
        _PERGUNTAS_SEM_ESCOPO["avisou"] = True
        logger.warning(
            "Magalu chat pulado: token sem escopo %s — reconceda OAuth "
            "(services:questions-seller:read/write) e regenere o refresh",
            ESCOPO_PERGUNTAS_READ,
        )
        incrementar("chat.falha", tags=["canal:magalu", "motivo:escopo_ausente"])
    return False


def ultima_listagem_auth_quebrada() -> bool:
    """True se a última listar_pedidos_detalhado falhou por 401/403/invalid_grant."""
    return bool(_ULTIMA_LISTAGEM_PEDIDOS.get("auth_quebrada"))


def _resposta_indica_auth_quebrada(resposta) -> bool:
    status = status_http(resposta)
    if status in (401, 403):
        return True
    texto = (getattr(resposta, "text", "") or "").lower()
    return "invalid_grant" in texto or "unauthorized" in texto


def _ping_pedidos(*, timeout: int = 15):
    """GET /seller/v1/orders — prova auth de vendas (open:order + X-Tenant-Id).

    Não usa /v0/questions: aquele host exige escopo services:* e falha 403
    mesmo com pedidos íntegros. Chat continua em listar_perguntas.
    """
    return _request_magalu(
        "GET",
        f"{BASE}/seller/v1/orders",
        params={"limit": 1},
        timeout=timeout,
    )


def probe_conexao() -> dict:
    """Diagnóstico sem mascarar erros HTTP como lista vazia."""
    if not _enabled():
        return {"ok": False, "status": 0, "msg": "Magalu não configurado"}
    try:
        r = _ping_pedidos(timeout=15)
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
        if status == 422:
            return {
                "ok": False,
                "status": 422,
                "msg": "X-Tenant-Id ausente ou inválido — confira MAGALU_CHANNEL_ID",
            }
        return {"ok": False, "status": status, "msg": (getattr(r, "text", "") or "")[:200]}
    except Exception as exc:
        logger.error("Magalu probe_conexao erro: %s", exc)
        return {"ok": False, "status": 0, "msg": str(exc)}


def _listar_perguntas_nao_respondidas_detalhado(limit: int = 20, max_paginas: int = 5) -> tuple[list[dict], bool]:
    """Retorna (perguntas, sucesso_chamada), percorrendo páginas via offset."""
    if not _enabled():
        logger.info("Magalu não configurado.")
        return [], False
    if not _pode_listar_perguntas():
        return [], False
    out: list[dict] = []
    offset = 0
    try:
        for _pagina in range(max(1, max_paginas)):
            r = _request_magalu(
                "GET",
                f"{BASE_SERVICES}/v0/questions",
                params={"status": "pending", "limit": limit, "offset": offset},
                timeout=20,
            )
            if status_http(r) != 200:
                if status_http(r) == 403:
                    _PERGUNTAS_SEM_ESCOPO["valor"] = True
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
        logger.info("Magalu não configurado para responder pergunta.")
        return False
    if not _pode_listar_perguntas():
        return False
    try:
        r = _request_magalu(
            "POST",
            f"{BASE_SERVICES}/v0/questions/{question_id}/answer",
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
        r = _ping_pedidos(timeout=20)
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
        return {
            "configurado": False,
            "pendencias": 0,
            "claims_rate": None,
            "claims_conhecido": False,
            "dias_sem_acesso": 999,
            "conta_id": str(MAGALU_SELLER_ID or "").strip(),
        }

    perguntas, ok = _listar_perguntas_nao_respondidas_detalhado(limit=50)
    if ok:
        registrar_acesso("magalu")

    return {
        "configurado": True,
        "api_ok": ok,
        "pendencias": len(perguntas),
        "claims_rate": None,
        "claims_conhecido": False,
        "dias_sem_acesso": dias_sem_acesso("magalu") or 0,
        "conta_id": str(MAGALU_SELLER_ID or "").strip(),
        "modelo": "sla_magalu",
    }


def atualizar_preco_item(sku: str, novo_preco: float) -> bool:
    from core.guardrails import bloqueio_escrita_global

    if bloqueio := bloqueio_escrita_global():
        logger.warning("Magalu atualizar_preco_item bloqueado: %s", bloqueio["erro"])
        return False
    if not _enabled():
        logger.info("Magalu não configurado para atualização de preço.")
        return False
    try:
        r = _request_magalu(
            "PUT",
            f"{BASE}/seller/products/{sku}/price",
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
        logger.info("Magalu não configurado para atualização de estoque.")
        return False
    try:
        r = _request_magalu(
            "PUT",
            f"{BASE}/seller/products/{sku}/stock",
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
    global _ULTIMA_LISTAGEM_PEDIDOS
    _ULTIMA_LISTAGEM_PEDIDOS = {"auth_quebrada": False, "status": 0}

    if not _enabled():
        logger.info("Magalu não configurado para listar pedidos.")
        return [], False

    out: list[dict] = []
    limite_data = datetime.now(timezone.utc) - timedelta(days=max(1, int(dias)))
    limit = 50
    offset = 0
    try:
        for _pagina in range(max(1, max_paginas)):
            r = _request_magalu(
                "GET",
                f"{BASE}/seller/v1/orders",
                params={"limit": limit, "offset": offset},
                timeout=25,
            )
            if status_http(r) != 200:
                status = status_http(r)
                auth_quebrada = _resposta_indica_auth_quebrada(r)
                _ULTIMA_LISTAGEM_PEDIDOS = {
                    "auth_quebrada": auth_quebrada,
                    "status": status,
                }
                if auth_quebrada:
                    try:
                        incrementar(
                            "magalu.auth_falha",
                            tags=[f"status_code:{status}", "origem:listar_pedidos"],
                        )
                    except Exception:
                        pass
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
