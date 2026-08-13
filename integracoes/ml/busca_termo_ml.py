"""
integracoes/ml/busca_termo_ml.py
Busca por termo no ML com fallbacks quando /sites/search retorna 403.

Ordem: products/search (catálogo oficial) → /sites/search (opt-in, costuma 403)
→ catálogo multi-ref → Brave Search (opcional) → DuckDuckGo → cache recente.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    ML_BUSCA_TERMO_CACHE_TTL_SEG,
    ML_BUSCA_TERMO_FALLBACK_BRAVE,
    ML_BUSCA_TERMO_FALLBACK_CACHE,
    ML_BUSCA_TERMO_FALLBACK_CATALOGO,
    ML_BUSCA_TERMO_FALLBACK_DDG,
    ML_BUSCA_TERMO_FALLBACK_PRODUCTS,
    ML_BUSCA_TERMO_SITES_SEARCH,
    ML_BUSCA_TERMO_MAX_PRODUCTS,
    ML_BUSCA_TERMO_MAX_REFS_CATALOGO,
    ML_SITE_ID,
    ROOT,
)
from core.datadog_metrics import incrementar
from core.ddg_lite import buscar as ddg_buscar
from integracoes.ml.busca_externa_brave import buscar_mercadolivre as brave_buscar_ml

logger = logging.getLogger("busca_termo_ml")

_MLB_ID_RE = re.compile(r"MLB-?\d+", re.I)
_PLACEHOLDER_IDS = frozenset({"", "MLB_PREENCHER"})
_CACHE_PATH = ROOT / "logs" / "ml_busca_termo_cache.json"


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


def _palavras_termo(termo: str) -> list[str]:
    return [p for p in termo.lower().split() if len(p) >= 3]


def _titulo_relevante(termo: str, titulo: str) -> bool:
    """
    Exige relevância mínima no título.
    - Termos curtos (1–2 palavras): qualquer match
    - Termos longos: pelo menos metade das palavras (≥2), preferindo marca/kit
    """
    palavras = _palavras_termo(termo)
    if not palavras:
        return True
    texto = (titulo or "").lower()
    if len(palavras) <= 2:
        return any(p in texto for p in palavras)

    hits = sum(1 for p in palavras if p in texto)
    minimo = max(2, (len(palavras) + 1) // 2)
    if hits < minimo:
        return False
    # Marcas/quantidades comuns: se presentes no termo, devem estar no título
    obrigatorias = {
        p
        for p in palavras
        if p in {"impala", "anita", "risque", "colorama", "dailus", "carmed", "mimo", "bailarina"}
        or (p.isdigit() and int(p) >= 3)
    }
    if obrigatorias and not all(p in texto for p in obrigatorias):
        return False
    return True


def filtrar_por_relevancia_titulo(termo: str, resultados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filtra resultados cujo título não casa com o termo de busca."""
    out: list[dict[str, Any]] = []
    for row in resultados or []:
        if not isinstance(row, dict):
            continue
        if _titulo_relevante(termo, str(row.get("titulo") or "")):
            out.append(row)
    return out


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


def _resolver_refs_catalogo(
    termo: str,
    item_id_referencia: str | None,
    *,
    listar_meus_fn: Callable[[], list[dict[str, Any]]],
) -> list[str]:
    refs: list[str] = []
    vistos: set[str] = set()

    def _add(iid: str | None) -> None:
        if not _item_id_valido(iid):
            return
        norm = str(iid).strip().upper().replace("-", "")
        if norm in vistos:
            return
        vistos.add(norm)
        refs.append(norm)

    _add(item_id_referencia)

    try:
        from core.catalogo_produtos import carregar_produtos_catalogo

        palavras_cat = _palavras_termo(termo)
        for prod in carregar_produtos_catalogo():
            ml = (prod.get("canais") or {}).get("mercadolivre") or {}
            if not ml.get("ativo", True):
                continue
            iid = str(ml.get("item_id") or "").strip()
            titulo = str(ml.get("titulo_anuncio") or prod.get("nome") or "")
            if palavras_cat and not any(p in titulo.lower() for p in palavras_cat):
                continue
            _add(iid)
            if len(refs) >= max(1, ML_BUSCA_TERMO_MAX_REFS_CATALOGO):
                return refs
    except Exception:
        pass

    palavras = _palavras_termo(termo)
    candidatos: list[tuple[int, str]] = []
    for an in listar_meus_fn() or []:
        iid = str(an.get("item_id") or an.get("id") or "").strip().upper().replace("-", "")
        if not _item_id_valido(iid):
            continue
        titulo = str(an.get("titulo") or an.get("title") or "").lower()
        score = sum(1 for p in palavras if p in titulo) if palavras else 1
        if score > 0:
            candidatos.append((score, iid))

    candidatos.sort(key=lambda x: x[0], reverse=True)
    for _, iid in candidatos:
        _add(iid)
        if len(refs) >= max(1, ML_BUSCA_TERMO_MAX_REFS_CATALOGO):
            break

    return refs[: max(1, ML_BUSCA_TERMO_MAX_REFS_CATALOGO)]


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
        try:
            incrementar("ml.busca.sites_search_403")
        except Exception:
            pass
        # Conhecido desde ~2025 (PolicyAgent). Não é incidente — fallback cobre.
        # Antes era WARNING e gerava centenas de warns/dia no Datadog.
        logger.info(
            "ML busca /sites/search HTTP 403 termo=%r — endpoint bloqueado; usando fallbacks",
            termo,
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
        if not _titulo_relevante(termo, str(norm.get("titulo") or "")):
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


def _buscar_via_products_api(termo: str, limite: int) -> list[dict[str, Any]]:
    """
    Alternativa ao /sites/search (403): usa catálogo oficial
    GET /products/search + GET /products/{id}/items — retorna preço e seller_id.
    """
    from integracoes.ml import ml_client

    if not ML_BUSCA_TERMO_FALLBACK_PRODUCTS or not ml_client._enabled():
        return []

    termo = (termo or "").strip()
    if not termo:
        return []

    seller_self = _seller_self()
    max_products = max(1, min(20, ML_BUSCA_TERMO_MAX_PRODUCTS))
    encontrados: list[dict[str, Any]] = []
    vistos: set[str] = set()

    try:
        r = ml_client._request_ml(
            "GET",
            f"{ml_client.BASE}/products/search",
            params={"status": "active", "site_id": ML_SITE_ID or "MLB", "q": termo},
            timeout=25,
        )
        if r.status_code != 200:
            logger.warning("ML products/search HTTP %s termo=%r", r.status_code, termo[:60])
            return []
        produtos = (r.json() or {}).get("results") or []
    except Exception as exc:
        logger.warning("ML products/search erro termo=%r: %s", termo[:60], exc)
        return []

    for prod in produtos[:max_products]:
        if not isinstance(prod, dict):
            continue
        pid = str(prod.get("id") or prod.get("catalog_product_id") or "").strip()
        nome_prod = str(prod.get("name") or "")
        catalog_created = str(prod.get("date_created") or "").strip() or None
        if not pid:
            continue
        if nome_prod and not _titulo_relevante(termo, nome_prod):
            # ainda tenta — catálogo às vezes usa nome genérico
            pass
        # products/search às vezes omite date_created — completa via /products/{id}
        if not catalog_created:
            try:
                rp = ml_client._request_ml("GET", f"{ml_client.BASE}/products/{pid}", timeout=15)
                if rp.status_code == 200:
                    body_p = rp.json() or {}
                    catalog_created = str(body_p.get("date_created") or "").strip() or None
                    if not nome_prod:
                        nome_prod = str(body_p.get("name") or "")
            except Exception:
                pass
        try:
            ri = ml_client._request_ml(
                "GET",
                f"{ml_client.BASE}/products/{pid}/items",
                timeout=20,
            )
            if ri.status_code != 200:
                continue
            itens = (ri.json() or {}).get("results") or []
        except Exception:
            continue

        for it in itens:
            if not isinstance(it, dict):
                continue
            item_id = str(it.get("item_id") or it.get("id") or "").strip().upper()
            if not item_id or item_id in vistos:
                continue
            seller_id = str(it.get("seller_id") or "")
            if seller_self and seller_id == seller_self:
                continue
            try:
                preco = float(it.get("price") or 0)
            except (TypeError, ValueError):
                preco = 0.0
            if preco <= 0:
                continue
            vistos.add(item_id)
            titulo = nome_prod or item_id
            try:
                vendidos = int(it.get("sold_quantity") or 0)
            except (TypeError, ValueError):
                vendidos = 0
            encontrados.append(
                {
                    "item_id": item_id,
                    "titulo": titulo,
                    "preco": preco,
                    "quantidade_vendida": vendidos,
                    "seller_id": seller_id,
                    "permalink": str(it.get("permalink") or f"https://produto.mercadolivre.com.br/{item_id}"),
                    "fonte_busca": "products_api",
                    "catalog_product_id": pid,
                    "catalog_date_created": catalog_created,
                    "listing_type_id": str(it.get("listing_type_id") or ""),
                }
            )
            if len(encontrados) >= limite:
                logger.info(
                    "ML busca termo=%r fonte=products_api resultados=%d",
                    termo[:60],
                    len(encontrados),
                )
                return encontrados

    if encontrados:
        logger.info(
            "ML busca termo=%r fonte=products_api resultados=%d",
            termo[:60],
            len(encontrados),
        )
    return encontrados


def _buscar_via_brave(termo: str, limite: int) -> list[dict[str, Any]]:
    if not ML_BUSCA_TERMO_FALLBACK_BRAVE:
        return []
    brutos = brave_buscar_ml(termo, limite=max(limite * 3, 15))
    if not brutos:
        return []

    encontrados: list[dict[str, Any]] = []
    for hit in brutos:
        url = hit.get("url") or ""
        titulo_ext = hit.get("titulo") or ""
        iid = extrair_item_id_ml(url) or extrair_item_id_ml(titulo_ext)
        if not iid:
            continue
        norm = _enriquecer_item(iid)
        if not norm:
            continue
        if not _titulo_relevante(termo, str(norm.get("titulo") or titulo_ext)):
            continue
        norm = dict(norm)
        norm["fonte_busca"] = "brave"
        encontrados.append(norm)
        if len(encontrados) >= limite:
            break
    return encontrados


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
        if not _titulo_relevante(termo, str(norm.get("titulo") or titulo_ddg)):
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

    refs = _resolver_refs_catalogo(
        termo,
        item_id_referencia,
        listar_meus_fn=ml_client.listar_meus_anuncios,
    )
    if not refs:
        return []

    combinado: list[dict[str, Any]] = []
    for ref in refs:
        linhas = ml_client.buscar_detalhes_concorrentes(ref, limite=limite)
        for row in linhas:
            norm = _normalizar_catalogo_para_busca(row)
            if _titulo_relevante(termo, norm.get("titulo", "")):
                combinado.append(norm)

    if combinado:
        logger.info(
            "ML busca termo=%r fallback catálogo refs=%s linhas=%d",
            termo,
            refs,
            len(combinado),
        )
    return combinado


def _chave_cache(termo: str) -> str:
    return termo.strip().lower()


def _ler_cache(termo: str, limite: int) -> list[dict[str, Any]]:
    if not ML_BUSCA_TERMO_FALLBACK_CACHE:
        return []
    data = ler_json(_CACHE_PATH, default={})
    if not isinstance(data, dict):
        return []
    entry = data.get(_chave_cache(termo))
    if not isinstance(entry, dict):
        return []
    ts = entry.get("timestamp")
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        idade = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
        if idade > max(60, ML_BUSCA_TERMO_CACHE_TTL_SEG):
            return []
    except (TypeError, ValueError):
        return []
    rows = entry.get("resultados") or []
    if not isinstance(rows, list):
        return []
    out = [dict(r, fonte_busca="cache") for r in rows if isinstance(r, dict)][:limite]
    if out:
        logger.info("ML busca termo=%r fonte=cache resultados=%d", termo, len(out))
    return out


def _gravar_cache(termo: str, resultados: list[dict[str, Any]]) -> None:
    if not ML_BUSCA_TERMO_FALLBACK_CACHE or not resultados:
        return
    try:
        data = ler_json(_CACHE_PATH, default={})
        if not isinstance(data, dict):
            data = {}
        data[_chave_cache(termo)] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "resultados": resultados,
        }
        escrever_json_atomico(_CACHE_PATH, data)
    except Exception as exc:
        logger.debug("ML busca cache não gravado termo=%r: %s", termo[:60], exc)


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

    # /products/search funciona com token; /sites/search costuma 403 (PolicyAgent).
    try:
        via_products = _buscar_via_products_api(termo, limite)
        if via_products:
            _gravar_cache(termo, via_products)
            return via_products
    except Exception as exc:
        logger.warning("ML products fallback erro termo=%r: %s", termo[:60], exc)

    if ML_BUSCA_TERMO_SITES_SEARCH:
        try:
            api = _buscar_via_api(termo, limite)
            if api:
                logger.info("ML busca termo=%r fonte=api resultados=%d", termo, len(api))
                _gravar_cache(termo, api)
                return api
        except Exception as exc:
            ml_client._log_erro_leitura_termo("buscar_concorrentes_por_termo", termo, exc)

    combinado: list[dict[str, Any]] = []
    combinado.extend(_buscar_via_catalogo(termo, limite, item_id_referencia))
    combinado.extend(_buscar_via_brave(termo, limite))

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
        _gravar_cache(termo, combinado)
        return combinado

    cache = _ler_cache(termo, limite)
    if cache:
        return cache

    logger.warning(
        "ML busca termo=%r sem resultados — API 403/bloqueada e fallbacks vazios "
        "(products/catálogo/brave/ddg/cache)",
        termo,
    )
    return []
