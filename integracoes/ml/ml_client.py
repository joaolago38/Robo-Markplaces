"""
integracoes/ml/ml_client.py
Cliente Mercado Livre com operações essenciais de perguntas/respostas.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from core.config import ML_ACCESS_TOKEN, ML_SELLER_ID
from core.http_client import request
from core.http_errors import log_http_erro_listagem, status_http
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


def _request_ml(method: str, url: str, *, timeout: int = 30, **kwargs: Any):
    """
    Request autenticado com retry único em 401 (renova token e repete).
    Rate limit (429) já é tratado pelo http_client (backoff).
    """
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update(_h())
    kwargs["headers"] = headers

    r = request(method, url, timeout=timeout, **kwargs)
    if r.status_code == 401:
        logger.warning("ML HTTP 401 — renovando token e repetindo request")
        headers["Authorization"] = f"Bearer {get_token_ml(forcar=True) or ML_ACCESS_TOKEN}"
        kwargs["headers"] = headers
        r = request(method, url, timeout=timeout, **kwargs)
    return r


def _executar_acao_status(
    item_id: str,
    status: str,
    acao: str,
    *,
    dry_run: bool = True,
    confirmar: bool = False,
) -> dict:
    """
    Altera o status de um anúncio (paused / active / closed).
    dry_run=True por padrão; confirmar=True obrigatório para executar de verdade.
    """
    item_id = (item_id or "").strip()
    if not item_id:
        return {"ok": False, "erro": "item_id ausente", "dry_run": dry_run, "acao": acao}
    if not _enabled():
        return {"ok": False, "erro": "Mercado Livre não configurado", "dry_run": dry_run, "acao": acao}

    if dry_run:
        logger.info("[DRY-RUN] ML %s item_id=%s -> status=%s", acao, item_id, status)
        return {
            "ok": True,
            "dry_run": True,
            "acao": acao,
            "item_id": item_id,
            "status": status,
        }

    if not confirmar:
        return {
            "ok": False,
            "dry_run": False,
            "acao": acao,
            "item_id": item_id,
            "erro": f"ação de escrita requer confirmar=True (ação: {acao})",
        }

    try:
        r = _request_ml(
            "PUT",
            f"{BASE}/items/{item_id}",
            json={"status": status},
            timeout=30,
        )
        r.raise_for_status()
        body = r.json() or {}
        logger.info("ML %s ok item_id=%s status=%s", acao, item_id, body.get("status", status))
        return {
            "ok": True,
            "dry_run": False,
            "acao": acao,
            "item_id": item_id,
            "status": str(body.get("status", status)),
        }
    except Exception as exc:
        logger.error("ML %s erro item_id=%s: %s", acao, item_id, exc)
        return {"ok": False, "dry_run": False, "acao": acao, "item_id": item_id, "erro": str(exc)}


def pausar_anuncio(item_id: str, *, dry_run: bool = True, confirmar: bool = False) -> dict:
    """Pausa um anúncio (status=paused). Não lança exceção."""
    return _executar_acao_status(item_id, "paused", "pausar", dry_run=dry_run, confirmar=confirmar)


def ativar_anuncio(item_id: str, *, dry_run: bool = True, confirmar: bool = False) -> dict:
    """Reativa um anúncio pausado (status=active). Não lança exceção."""
    return _executar_acao_status(item_id, "active", "ativar", dry_run=dry_run, confirmar=confirmar)


def encerrar_anuncio(item_id: str, *, dry_run: bool = True, confirmar: bool = False) -> dict:
    """
    Encerra um anúncio (status=closed) — praticamente irreversível.
    Exige confirmar=True quando dry_run=False.
    """
    return _executar_acao_status(item_id, "closed", "encerrar", dry_run=dry_run, confirmar=confirmar)


def obter_status_anuncio(item_id: str) -> dict:
    """Lê o status atual de um anúncio. Retorna {ok, item_id, status, titulo} ou {ok: False, erro}."""
    item_id = (item_id or "").strip()
    if not item_id or not _enabled():
        return {"ok": False, "erro": "item_id ausente ou ML não configurado"}
    try:
        r = _request_ml("GET", f"{BASE}/items/{item_id}", timeout=20)
        r.raise_for_status()
        body = r.json() or {}
        return {
            "ok": True,
            "item_id": item_id,
            "status": str(body.get("status", "") or ""),
            "titulo": str(body.get("title", "") or ""),
        }
    except Exception as exc:
        logger.error("ML obter_status_anuncio erro item_id=%s: %s", item_id, exc)
        return {"ok": False, "item_id": item_id, "erro": str(exc)}

def probe_conexao() -> dict:
    """Diagnóstico sem mascarar erros HTTP."""
    if not _enabled():
        return {"ok": False, "status": 0, "msg": "Mercado Livre não configurado"}
    try:
        r = request("GET", f"{BASE}/users/me", headers=_h(), timeout=15)
        status = getattr(r, "status_code", 0)
        if status == 200:
            return {"ok": True, "status": 200, "msg": "autenticado"}
        if status == 401:
            return {"ok": False, "status": 401, "msg": "token expirado ou inválido"}
        if status == 403:
            return {
                "ok": False,
                "status": 403,
                "msg": "sem permissão — verifique escopos do app ML",
            }
        return {"ok": False, "status": status, "msg": (getattr(r, "text", "") or "")[:200]}
    except Exception as exc:
        logger.error("ML probe_conexao erro: %s", exc)
        return {"ok": False, "status": 0, "msg": str(exc)}


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
        if status_http(r) != 200:
            log_http_erro_listagem(logger, "ML listar_perguntas_nao_respondidas", r)
            return []
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
            timeout=30,
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
        if status_http(r) != 200:
            log_http_erro_listagem(logger, "ML buscar_reputacao_vendedor", r)
            return {}
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
            timeout=30,
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
            timeout=30,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.error("ML atualizar_estoque_item erro item_id=%s: %s", item_id, exc)
        return False


def listar_pedidos(dias: int = 7) -> list[dict]:
    """
    Busca pedidos dos últimos X dias do vendedor.
    Retorna lista com order_id, status, total, data e SKUs dos itens.
    Nunca lança exceção.
    """
    if not _enabled():
        logger.warning("Mercado Livre não configurado para listar pedidos.")
        return []
    try:
        tz = timezone(timedelta(hours=-3))
        data_from = (datetime.now(tz) - timedelta(days=dias)).isoformat()
        r = request(
            "GET",
            f"{BASE}/orders/search",
            headers=_h(),
            params={
                "seller": ML_SELLER_ID,
                "order.status": "paid",
                "sort": "date_desc",
                "date_created.from": data_from,
            },
            timeout=20,
        )
        if status_http(r) != 200:
            log_http_erro_listagem(logger, "ML listar_pedidos", r)
            return []
        results = r.json().get("results", []) or []
        out: list[dict] = []
        for o in results:
            if not isinstance(o, dict):
                continue
            out.append(
                {
                    "order_id": str(o.get("id", "")),
                    "status": o.get("status", ""),
                    "total": float(o.get("total_amount", 0) or 0),
                    "data": o.get("date_created", ""),
                    "itens": [
                        {
                            "sku": item.get("item", {}).get("seller_sku", ""),
                            "item_id": item.get("item", {}).get("id", ""),
                            "quantidade": item.get("quantity", 0),
                            "preco_unitario": float(item.get("unit_price", 0) or 0),
                        }
                        for item in (o.get("order_items") or [])
                        if isinstance(item, dict)
                    ],
                }
            )
        return out
    except Exception as exc:
        logger.error("ML listar_pedidos erro: %s", exc)
        return []


def buscar_metricas_item(item_id: str) -> dict:
    """
    Busca visitas e métricas de exposição de um anúncio específico.
    Retorna dict com visitas_7d, visitas_30d e status do anúncio.
    Nunca lança exceção.
    """
    if not _enabled() or not (item_id or "").strip():
        return {}
    try:
        item_id = item_id.strip()
        r_item = request("GET", f"{BASE}/items/{item_id}", headers=_h(), timeout=20)
        r_item.raise_for_status()
        item = r_item.json() or {}

        r7 = request(
            "GET",
            f"{BASE}/items/{item_id}/visits/time_window",
            headers=_h(),
            params={"last": 7, "unit": "day"},
            timeout=20,
        )
        r7.raise_for_status()
        v7 = int((r7.json() or {}).get("total_visits", 0) or 0)

        r30 = request(
            "GET",
            f"{BASE}/items/{item_id}/visits/time_window",
            headers=_h(),
            params={"last": 30, "unit": "day"},
            timeout=20,
        )
        r30.raise_for_status()
        v30 = int((r30.json() or {}).get("total_visits", 0) or 0)

        estoque_raw = item.get("available_quantity", 0)
        try:
            estoque_int = int(estoque_raw)
        except (TypeError, ValueError):
            estoque_int = int(float(estoque_raw or 0))

        return {
            "item_id": item_id,
            "titulo": str(item.get("title", "") or ""),
            "status": str(item.get("status", "") or ""),
            "preco": float(item.get("price", 0) or 0),
            "estoque": estoque_int,
            "visitas_7d": v7,
            "visitas_30d": v30,
        }
    except Exception as exc:
        logger.error("ML buscar_metricas_item erro item_id=%s: %s", item_id, exc)
        return {}


def _extrair_seller_id(row: dict) -> str:
    sid = row.get("seller_id")
    if sid is None and isinstance(row.get("seller"), dict):
        sid = row["seller"].get("id")
    return str(sid).strip() if sid is not None else ""


def _listar_linhas_concorrentes_catalogo(item_id: str) -> list[dict]:
    """Retorna linhas de concorrentes ativos no catálogo (exclui o próprio vendedor)."""
    if not _enabled() or not (item_id or "").strip():
        return []
    item_id = item_id.strip()
    ri = request("GET", f"{BASE}/items/{item_id}", headers=_h(), timeout=20)
    ri.raise_for_status()
    body = ri.json() or {}
    catalog_pid = body.get("catalog_product_id")
    if not catalog_pid:
        return []

    rp = request(
        "GET",
        f"{BASE}/products/{catalog_pid}/items",
        headers=_h(),
        params={"status": "active"},
        timeout=20,
    )
    rp.raise_for_status()
    pdata = rp.json() or {}
    results = pdata.get("results") or pdata.get("items") or []

    seller_self = str(ML_SELLER_ID or "").strip()
    concorrentes: list[dict] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        if _extrair_seller_id(row) == seller_self:
            continue
        concorrentes.append(row)
    return concorrentes


def _normalizar_concorrente(row: dict) -> dict:
    shipping = row.get("shipping") or {}
    try:
        preco = float(row.get("price") or 0)
    except (TypeError, ValueError):
        preco = 0.0
    try:
        vendidos = int(row.get("sold_quantity", 0) or 0)
    except (TypeError, ValueError):
        vendidos = 0
    return {
        "id": str(row.get("id", "") or ""),
        "titulo": str(row.get("title", "") or ""),
        "preco": preco,
        "frete_gratis": bool(shipping.get("free_shipping", False)),
        "condicao": str(row.get("condition", "") or ""),
        "quantidade_vendida": vendidos,
    }


def buscar_detalhes_concorrentes(item_id: str, limite: int = 5) -> list[dict]:
    """
    Lista concorrentes no mesmo catálogo com título, preço, frete, condição e vendas.
    Retorna lista vazia em caso de erro. Nunca lança exceção.
    """
    if not _enabled() or not (item_id or "").strip():
        return []
    try:
        linhas = _listar_linhas_concorrentes_catalogo(item_id)
        detalhes: list[dict] = []
        for row in linhas[: max(0, limite)]:
            norm = _normalizar_concorrente(row)
            if norm.get("preco", 0) > 0:
                detalhes.append(norm)
        return detalhes
    except Exception as exc:
        logger.error("ML buscar_detalhes_concorrentes erro item_id=%s: %s", item_id, exc)
        return []


def buscar_menor_preco_concorrente(item_id: str) -> float:
    """
    Busca o menor preço praticado por outros vendedores no mesmo anúncio/produto.
    Retorna 0.0 se não encontrar ou em caso de erro.
    Nunca lança exceção.
    """
    if not _enabled() or not (item_id or "").strip():
        return 0.0
    try:
        precos: list[float] = []
        for row in _listar_linhas_concorrentes_catalogo(item_id):
            try:
                p = float(row.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if p > 0:
                precos.append(p)
        return min(precos) if precos else 0.0
    except Exception as exc:
        logger.error("ML buscar_menor_preco_concorrente erro item_id=%s: %s", item_id, exc)
        return 0.0


def buscar_acos_ads(item_id: str, dias: int = 14) -> float:
    """
    Busca o ACOS (custo de anúncio / receita) atual das campanhas de Product Ads.
    Retorna 0.0 se não houver campanha ativa ou em caso de erro.
    Nunca lança exceção.
    """
    if not _enabled() or not (item_id or "").strip():
        return 0.0
    try:
        item_id = item_id.strip()
        tz = timezone(timedelta(hours=-3))
        hoje = datetime.now(tz).date()
        date_from = (hoje - timedelta(days=dias)).isoformat()
        date_to = hoje.isoformat()

        r = request(
            "GET",
            f"{BASE}/advertising/product_ads",
            headers=_h(),
            params={
                "item_id": item_id,
                "date_from": date_from,
                "date_to": date_to,
            },
            timeout=20,
        )
        r.raise_for_status()
        results = (r.json() or {}).get("results") or []
        total_spend = 0.0
        total_revenue = 0.0
        for row in results:
            if not isinstance(row, dict):
                continue
            total_spend += float(row.get("ad_spend", 0) or 0)
            total_revenue += float(row.get("revenue", 0) or 0)
        if total_revenue <= 0:
            return 0.0
        return round(total_spend / total_revenue, 4)
    except Exception as exc:
        logger.error("ML buscar_acos_ads erro item_id=%s: %s", item_id, exc)
        return 0.0


def listar_meus_anuncios() -> list[dict]:
    """
    Lista todos os anúncios ativos do vendedor com item_id, título, preço e SKU.
    Útil para mapear item_ids no catalogo/produtos.json.
    Nunca lança exceção.
    """
    if not _enabled():
        logger.warning("Mercado Livre não configurado para listar anúncios.")
        return []
    try:
        item_ids: list[str] = []
        offset = 0
        while True:
            r = request(
                "GET",
                f"{BASE}/users/{ML_SELLER_ID}/items/search",
                headers=_h(),
                params={"status": "active", "limit": 100, "offset": offset},
                timeout=20,
            )
            r.raise_for_status()
            chunk = r.json().get("results", []) or []
            if not chunk:
                break
            for raw_id in chunk:
                item_ids.append(str(raw_id))
            if len(chunk) < 100:
                break
            offset += 100

        normalized: list[dict] = []
        batch_size = 20
        attrs = "id,title,price,seller_sku,status"
        for i in range(0, len(item_ids), batch_size):
            batch = item_ids[i : i + batch_size]
            rm = request(
                "GET",
                f"{BASE}/items",
                headers=_h(),
                params={"ids": ",".join(batch), "attributes": attrs},
                timeout=20,
            )
            rm.raise_for_status()
            payload = rm.json()
            if not isinstance(payload, list):
                continue
            for entry in payload:
                if not isinstance(entry, dict) or entry.get("code") != 200:
                    continue
                b = entry.get("body")
                if not isinstance(b, dict):
                    continue
                normalized.append(
                    {
                        "item_id": str(b.get("id", "")),
                        "titulo": str(b.get("title", "") or ""),
                        "preco": float(b.get("price", 0) or 0),
                        "sku": str(b.get("seller_sku", "") or ""),
                        "status": str(b.get("status", "") or ""),
                    }
                )
        return normalized
    except Exception as exc:
        logger.error("ML listar_meus_anuncios erro: %s", exc)
        return []
