"""
integracoes/ml/busca_termo_ml.py
Busca por termo no ML com fallbacks quando /sites/search retorna 403.

Ordem: API autenticada → catálogo (/products/.../items) → DuckDuckGo + enriquecimento /items/{id}.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from core.config import ML_BUSCA_TERMO_FALLBACK_CATALOGO, ML_BUSCA_TERMO_FALLBACK_DDG, ML_SITE_ID
from core.ddg_lite import buscar as ddg_buscar

logger = logging.getLogger("busca_termo_ml")

_MLB_ID_RE = re.compile(r"MLB-?\d+", re.I)
_PLACEHOLDER_IDS = frozenset({"", "MLB_PREENCHER"})


def extrair_item_id_ml(texto: str) -> str | None:
    """Extrai MLB123456 de URL ou texto (aceita MLB-123456)."""
    if not texto:
        return None
    m = _MLB_ID_RE.search(texto)
    if not m:
        return None
    return m.group(0).upper().replace("-", "")


def _item_id_valido(item_id: str | None) -> bool:
    iid = (item_id or "").strip().upper().replace("-", "")
    return bool(iid) and iid not in _PLACEHOLDER_IDS


def _seller_self() -> str:
    from integracoes.ml import ml_client

    return str(ml_client.ML_SELLER_ID or "").strip()


def _normalizar_catalogo_para_busca(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": str(row.get("id") or row.get("item_id") or ""),
        "titulo": str(row.get("titulo") or ""),
        "preco": float(row.get("preco") or 0),
        "frete_gratis": bool(row.get("frete_gratis", False)),
        "condicao": str(row.get("condicao") or ""),
        "quantidade_vendida": int(row.get("quantidade_vendida") or 0),
        "seller_id": str(row.get("seller_id") or ""),
        "permalink": str(row.get("permalink") or ""),
        "fonte_busca": "catalogo",
    }


def _dedupe_por_item(lista: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vistos: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in lista:
        iid = str(row.get("item_id") or "").strip()
        if not iid or iid in vistos:
            continue
        vistos.add(iid)
        out.append(row)
    return out


def _resolver_item_referencia(
    termo: str,
    item_id_referencia: str | None,
    *,
    listar_meus_fn: Callable[[], list[dict[str, Any]]],
) -> str | None:
    if _item_id_valido(item_id_referencia):
        return str(item_id_referencia).strip().upper().replace("-", "")

    palavras = [p for p in termo.lower().split() if len(p) >= 4]
    if not palavras:
        return None

    melhor_id: str | None = None
    melhor_score = 0
    for an in listar_meus_fn() or []:
        iid = str(an.get("item_id") or an.get("id") or "").strip().upper().replace("-", "")
        if not _item_id_valido(iid):
            continue
        titulo = str(an.get("titulo") or an.get("title") or "").lower()
        score = sum(1 for p in palavras if p in titulo)
        if score > melhor_score:
            melhor_score = score
            melhor_id = iid
    return melhor_id if melhor_score >= 2 else None


def _buscar_via_api(termo: str, limite: int) -> list[dict[str, Any]]:
    from integracoes.ml import ml_client

    seller_self = _seller_self()
    url = f"{ml_client.BASE}/sites/{ML_SITE_ID}/search"
    params = {"q": termo, "limit": limite}

    if ml_client._enabled():
        r = ml_client._request_ml("GET", url, params=params, timeout=20)
    else:
        from core.http_client import request

        r = request("GET", url, params=params, timeout=20)

    if r.status_code == 403:
        ml_client._log_erro_leitura_termo(
            "buscar_concorrentes_por_termo",
            termo,
            ml_client._http_error_from_response(r),
        )
        return []

    r.raise_for_status()
    body = r.json() or {}
    results = body.get("results") or []
    encontrados: list[dict[str, Any]] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        norm = ml_client._normalizar_resultado_busca(row)
        norm["fonte_busca"] = "api"
        if seller_self and norm["seller_id"] == seller_self:
            continue
        if norm["preco"] > 0:
            encontrados.append(norm)
        if len(encontrados) >= limite:
            break
    return encontrados


def _enriquecer_item(item_id: str) -> dict[str, Any] | None:
    from integracoes.ml import ml_client

    if not ml_client._enabled():
        return None

    seller_self = _seller_self()
    try:
        r = ml_client._request_ml("GET", f"{ml_client.BASE}/items/{item_id}", timeout=20)
        if r.status_code in (403, 404):
            return None
        r.raise_for_status()
        norm = ml_client._normalizar_resultado_busca(r.json() or {})
        if seller_self and norm.get("seller_id") == seller_self:
            return None
        if float(norm.get("preco") or 0) <= 0:
            return None
        return norm
    except Exception:
        return None


def _buscar_via_ddg(termo: str, limite: int) -> list[dict[str, Any]]:
    query = f"site:mercadolivre.com.br {termo}"
    brutos = ddg_buscar(query, max_resultados=max(limite * 3, 15), contexto="ml_busca_termo")
    if not brutos:
        return []

    encontrados: list[dict[str, Any]] = []
    for hit in brutos:
        url = hit.get("url") or hit.get("link") or ""
        titulo_ddg = hit.get("title") or hit.get("titulo") or ""
        iid = extrair_item_id_ml(url) or extrair_item_id_ml(titulo_ddg)
        if not iid:
            continue
        norm = _enriquecer_item(iid)
        if not norm:
            continue
        norm = dict(norm)
        norm["fonte_busca"] = "ddg"
        encontrados.append(norm)
        if len(encontrados) >= limite:
            break
    return encontrados


def _buscar_via_catalogo(termo: str, limite: int, item_id_referencia: str | None) -> list[dict[str, Any]]:
    from integracoes.ml import ml_client

    if not ML_BUSCA_TERMO_FALLBACK_CATALOGO or not ml_client._enabled():
        return []

    ref = _resolver_item_referencia(
        termo,
        item_id_referencia,
        listar_meus_fn=ml_client.listar_meus_anuncios,
    )
    if not ref:
        return []

    linhas = ml_client.buscar_detalhes_concorrentes(ref, limite=limite)
    if not linhas:
        return []

    logger.info("ML busca termo=%r fallback catálogo item_ref=%s linhas=%d", termo, ref, len(linhas))
    return [_normalizar_catalogo_para_busca(row) for row in linhas]


def executar_busca_termo(
    termo: str,
    limite: int = 10,
    *,
    item_id_referencia: str | None = None,
) -> list[dict[str, Any]]:
    """
    Busca anúncios ML por palavra-chave com fallbacks.
    Nunca lança exceção.
    """
    from integracoes.ml import ml_client

    termo = (termo or "").strip()
    if not termo:
        return []

    limite = max(1, min(50, limite))

    try:
        api = _buscar_via_api(termo, limite)
        if api:
            logger.info("ML busca termo=%r fonte=api resultados=%d", termo, len(api))
            return api
    except Exception as exc:
        ml_client._log_erro_leitura_termo("buscar_concorrentes_por_termo", termo, exc)

    combinado: list[dict[str, Any]] = []
    combinado.extend(_buscar_via_catalogo(termo, limite, item_id_referencia))

    if ML_BUSCA_TERMO_FALLBACK_DDG:
        combinado.extend(_buscar_via_ddg(termo, limite))

    combinado = _dedupe_por_item(combinado)[:limite]
    if combinado:
        fontes = sorted({str(r.get("fonte_busca") or "?") for r in combinado})
        logger.info(
            "ML busca termo=%r fonte=%s resultados=%d",
            termo,
            "+".join(fontes),
            len(combinado),
        )
        return combinado

    logger.warning(
        "ML busca termo=%r sem resultados — API 403/bloqueada e fallbacks vazios (catálogo/ddg)",
        termo,
    )
    return []
