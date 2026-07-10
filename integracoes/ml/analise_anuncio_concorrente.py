"""
integracoes/ml/analise_anuncio_concorrente.py
Métricas estilo LojaHub para anúncios/concorrentes no ML — sem scraping.

Fontes oficiais / estimativas:
  - preço, seller, listing_type: /products/{id}/items
  - data do catálogo: /products/{id}
  - avaliações / nota: /reviews/item/{item_id}
  - vendas: sold_quantity quando a API devolver (hoje costuma vir vazio)
  - vendas/dia, receita bruta/líquida: calculadas
  - visitas: só dos *seus* anúncios (API /visits)

Nunca lança exceção nas APIs públicas do módulo.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.config import (
    ML_ANALISE_ANUNCIO_MAX_ENRIQUECER,
    ML_ANALISE_ANUNCIO_TAXA_PCT,
    ML_SELLER_ID,
)
from core.http_client import request
from integracoes.ml import ml_client

logger = logging.getLogger("analise_anuncio_concorrente")

BASE = "https://api.mercadolibre.com"


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _i(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default


def dias_desde(iso_ts: str | None) -> int | None:
    """Dias decorridos desde uma data ISO (UTC). None se inválida."""
    raw = (iso_ts or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        agora = datetime.now(timezone.utc)
        dias = int((agora - dt.astimezone(timezone.utc)).total_seconds() // 86400)
        return max(0, dias)
    except Exception:
        return None


def estimar_vendas_por_dia(vendas: int | float, dias: int | None) -> float | None:
    """Vendas/dia ≈ vendas ÷ dias (mín. 1 dia). None se sem base."""
    v = _i(vendas)
    if v <= 0 or dias is None:
        return None
    return round(v / max(1, int(dias)), 2)


def estimar_receitas(
    preco: float,
    vendas: int | float,
    *,
    taxa_pct: float | None = None,
) -> dict[str, float | None]:
    """
    Receita bruta = preço × vendas.
    Receita líquida/un. = preço × (1 − taxa).
    Receita líquida total = líquida/un. × vendas.
    """
    p = _f(preco)
    v = _i(vendas)
    taxa = _f(taxa_pct if taxa_pct is not None else ML_ANALISE_ANUNCIO_TAXA_PCT, 13.0)
    taxa = max(0.0, min(99.0, taxa))
    liquida_un = round(p * (1.0 - taxa / 100.0), 2) if p > 0 else None
    bruta = round(p * v, 2) if p > 0 and v > 0 else None
    liquida_total = round((liquida_un or 0) * v, 2) if liquida_un is not None and v > 0 else None
    return {
        "taxa_estimada_pct": taxa,
        "receita_liquida_un": liquida_un,
        "receita_bruta_total": bruta,
        "receita_liquida_total": liquida_total,
    }


def buscar_reviews_item(item_id: str) -> dict[str, Any]:
    """Reviews/nota públicos. Nunca lança."""
    iid = str(item_id or "").strip().upper()
    if not iid:
        return {"ok": False, "motivo": "item_id vazio"}
    try:
        headers = ml_client._h() if ml_client._enabled() else {}
        r = request("GET", f"{BASE}/reviews/item/{iid}", headers=headers, params={"limit": 1}, timeout=20)
        if r.status_code != 200:
            return {"ok": False, "motivo": f"HTTP {r.status_code}", "item_id": iid}
        body = r.json() or {}
        paging = body.get("paging") or {}
        return {
            "ok": True,
            "item_id": iid,
            "avaliacoes": _i(paging.get("total")),
            "nota": _f(body.get("rating_average")),
            "estrelas": _i(body.get("stars")),
            "niveis": body.get("rating_levels") or {},
        }
    except Exception as exc:
        logger.warning("reviews item=%s: %s", iid, exc)
        return {"ok": False, "motivo": str(exc), "item_id": iid}


def buscar_meta_catalogo(catalog_product_id: str) -> dict[str, Any]:
    """Nome + date_created do produto de catálogo. Nunca lança."""
    pid = str(catalog_product_id or "").strip()
    if not pid:
        return {"ok": False, "motivo": "catalog_product_id vazio"}
    if not ml_client._enabled():
        return {"ok": False, "motivo": "ML sem credenciais"}
    try:
        r = ml_client._request_ml("GET", f"{BASE}/products/{pid}", timeout=20)
        if r.status_code != 200:
            return {"ok": False, "motivo": f"HTTP {r.status_code}", "catalog_product_id": pid}
        body = r.json() or {}
        return {
            "ok": True,
            "catalog_product_id": pid,
            "nome": str(body.get("name") or ""),
            "date_created": str(body.get("date_created") or ""),
            "status": str(body.get("status") or ""),
            "domain_id": str(body.get("domain_id") or ""),
            "permalink": str(body.get("permalink") or ""),
        }
    except Exception as exc:
        logger.warning("meta catalogo %s: %s", pid, exc)
        return {"ok": False, "motivo": str(exc), "catalog_product_id": pid}


def buscar_visitas_se_proprio(item_id: str, seller_id: str | None = None) -> dict[str, Any]:
    """
    Visitas só quando o anúncio é da conta autenticada (ML_SELLER_ID).
    Concorrente → indisponível via API oficial.
    """
    iid = str(item_id or "").strip().upper()
    sid = str(seller_id or "").strip()
    self_id = str(ML_SELLER_ID or "").strip()
    if not iid:
        return {"ok": False, "motivo": "item_id vazio", "disponivel": False}
    if self_id and sid and sid != self_id:
        return {
            "ok": True,
            "disponivel": False,
            "motivo": "visitas de terceiros não disponíveis na API oficial",
            "visitas_7d": None,
            "visitas_30d": None,
        }
    if not self_id or (sid and sid != self_id):
        # sem seller no row: tenta mesmo assim; API falha se não for nosso
        pass
    metricas = ml_client.buscar_metricas_item(iid) if ml_client._enabled() else {}
    if not metricas:
        return {
            "ok": True,
            "disponivel": False,
            "motivo": "visitas indisponíveis (não é anúncio próprio ou API bloqueada)",
            "visitas_7d": None,
            "visitas_30d": None,
        }
    return {
        "ok": True,
        "disponivel": True,
        "visitas_7d": _i(metricas.get("visitas_7d")),
        "visitas_30d": _i(metricas.get("visitas_30d")),
        "estoque": metricas.get("estoque"),
        "status": metricas.get("status"),
    }


def montar_metricas(
    *,
    preco: float,
    vendas: int = 0,
    date_created: str | None = None,
    taxa_pct: float | None = None,
    reviews: dict[str, Any] | None = None,
    visitas: dict[str, Any] | None = None,
    catalog_date_created: str | None = None,
) -> dict[str, Any]:
    """Monta o bloco de métricas (puro, sem I/O)."""
    dias_anuncio = dias_desde(date_created)
    dias_catalogo = dias_desde(catalog_date_created)
    # Prefere idade do anúncio; senão do catálogo (como LojaHub usa para vendas/dia)
    dias_base = dias_anuncio if dias_anuncio is not None else dias_catalogo
    vendas_i = _i(vendas)
    rec = estimar_receitas(preco, vendas_i, taxa_pct=taxa_pct)
    rev = reviews or {}
    vis = visitas or {}
    return {
        "preco": round(_f(preco), 2),
        "vendas": vendas_i if vendas_i > 0 else None,
        "vendas_por_dia": estimar_vendas_por_dia(vendas_i, dias_base),
        "dias_anuncio": dias_anuncio,
        "dias_catalogo": dias_catalogo,
        "anuncio_criado": date_created or None,
        "catalogo_criado": catalog_date_created or None,
        "avaliacoes": rev.get("avaliacoes") if rev.get("ok") else None,
        "nota": rev.get("nota") if rev.get("ok") else None,
        "visitas_7d": vis.get("visitas_7d") if vis.get("disponivel") else None,
        "visitas_30d": vis.get("visitas_30d") if vis.get("disponivel") else None,
        "visitas_disponivel": bool(vis.get("disponivel")),
        **rec,
        "fonte_metricas": "estimativa_oficial",
        "limitacao": (
            "Vendas/visitas de terceiros dependem da API; "
            "receita líquida usa taxa estimada; visitas só dos seus anúncios."
        ),
    }


def enriquecer_anuncio(
    anuncio: dict[str, Any],
    *,
    taxa_pct: float | None = None,
    buscar_reviews: bool = True,
    buscar_catalogo: bool = True,
    buscar_visitas: bool = True,
    cache_catalogo: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Acrescenta chave `metricas` ao anúncio (cópia rasa + metricas).
    """
    row = dict(anuncio or {})
    item_id = str(row.get("item_id") or row.get("id") or "").strip().upper()
    seller_id = str(row.get("seller_id") or "").strip()
    preco = _f(row.get("preco") or row.get("price"))
    vendas = _i(row.get("quantidade_vendida") or row.get("sold_quantity"))
    catalog_id = str(row.get("catalog_product_id") or "").strip()
    date_created = str(row.get("date_created") or "").strip() or None
    catalog_created = str(row.get("catalog_date_created") or "").strip() or None

    reviews: dict[str, Any] = {}
    if buscar_reviews and item_id:
        reviews = buscar_reviews_item(item_id)

    if buscar_catalogo and catalog_id and not catalog_created:
        cache = cache_catalogo if cache_catalogo is not None else {}
        if catalog_id not in cache:
            cache[catalog_id] = buscar_meta_catalogo(catalog_id)
        meta = cache[catalog_id]
        if meta.get("ok"):
            catalog_created = meta.get("date_created") or None
            if not row.get("titulo") and meta.get("nome"):
                row["titulo"] = meta["nome"]
            row["catalog_date_created"] = catalog_created
            row["catalog_nome"] = meta.get("nome")

    visitas: dict[str, Any] = {}
    if buscar_visitas and item_id:
        visitas = buscar_visitas_se_proprio(item_id, seller_id)

    row["metricas"] = montar_metricas(
        preco=preco,
        vendas=vendas,
        date_created=date_created,
        taxa_pct=taxa_pct,
        reviews=reviews,
        visitas=visitas,
        catalog_date_created=catalog_created,
    )
    if reviews.get("ok"):
        row["avaliacoes"] = reviews.get("avaliacoes")
        row["nota"] = reviews.get("nota")
    return row


def enriquecer_lista(
    anuncios: list[dict[str, Any]],
    *,
    limite: int | None = None,
    taxa_pct: float | None = None,
) -> list[dict[str, Any]]:
    """Enriquece até `limite` anúncios (reviews/catálogo); demais só com cálculo local."""
    max_n = limite if limite is not None else ML_ANALISE_ANUNCIO_MAX_ENRIQUECER
    max_n = max(0, int(max_n))
    cache: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for idx, a in enumerate(anuncios or []):
        if not isinstance(a, dict):
            continue
        full = idx < max_n
        out.append(
            enriquecer_anuncio(
                a,
                taxa_pct=taxa_pct,
                buscar_reviews=full,
                buscar_catalogo=full,
                buscar_visitas=full,
                cache_catalogo=cache,
            )
        )
    return out


def analisar_por_termo(
    termo: str,
    *,
    limite: int = 10,
    taxa_pct: float | None = None,
) -> dict[str, Any]:
    """Busca concorrentes por termo e enriquece com métricas estimadas."""
    termo = (termo or "").strip()
    if not termo:
        return {"ok": False, "motivo": "termo vazio", "anuncios": []}
    try:
        brutos = ml_client.buscar_concorrentes_por_termo(termo, limite=limite)
    except Exception as exc:
        logger.error("analisar_por_termo busca: %s", exc)
        return {"ok": False, "motivo": str(exc), "termo": termo, "anuncios": []}
    enriquecidos = enriquecer_lista(brutos, limite=limite, taxa_pct=taxa_pct)
    return {
        "ok": True,
        "termo": termo,
        "total": len(enriquecidos),
        "anuncios": enriquecidos,
        "taxa_estimada_pct": _f(taxa_pct if taxa_pct is not None else ML_ANALISE_ANUNCIO_TAXA_PCT),
    }


def montar_mensagem_metricas(analise: dict[str, Any], *, max_linhas: int = 8) -> str:
    """Resumo texto (Telegram/WhatsApp) das métricas enriquecidas."""
    linhas = [
        "📊 *Métricas anúncios ML (estimadas)*",
        f"Termo: `{analise.get('termo') or '?'}`",
        f"Amostra: *{analise.get('total', 0)}* | taxa est. {analise.get('taxa_estimada_pct', '?')}%",
        "",
    ]
    for a in (analise.get("anuncios") or [])[:max_linhas]:
        m = a.get("metricas") or {}
        titulo = (a.get("titulo") or a.get("item_id") or "?")[:48]
        preco = m.get("preco") or a.get("preco") or 0
        pedacos = [f"*{titulo}*", f"R$ {float(preco):.2f}"]
        if m.get("vendas") is not None:
            pedacos.append(f"vendas {m['vendas']}")
        if m.get("vendas_por_dia") is not None:
            pedacos.append(f"{m['vendas_por_dia']}/dia")
        if m.get("avaliacoes") is not None:
            nota = m.get("nota")
            pedacos.append(f"★{nota} ({m['avaliacoes']})" if nota else f"{m['avaliacoes']} aval.")
        if m.get("receita_liquida_un") is not None:
            pedacos.append(f"líq./un R$ {m['receita_liquida_un']:.2f}")
        if m.get("visitas_disponivel") and m.get("visitas_7d") is not None:
            pedacos.append(f"visitas7d {m['visitas_7d']}")
        linhas.append("• " + " | ".join(str(p) for p in pedacos))
    linhas.extend(
        [
            "",
            "_Receita líquida = preço − taxa estimada. Visitas só dos seus anúncios._",
        ]
    )
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse

    from core.atomic_io import escrever_json_atomico
    from core.config import ROOT

    parser = argparse.ArgumentParser(description="Métricas estimadas de anúncios ML (estilo LojaHub)")
    parser.add_argument("--termo", default="kit 5 esmaltes impala bailarina")
    parser.add_argument("--limite", type=int, default=5)
    parser.add_argument("--item", default="", help="Enriquece um item_id isolado (opcional)")
    parser.add_argument("--catalog", default="", help="catalog_product_id opcional com --item")
    parser.add_argument("--telegram", action="store_true")
    args = parser.parse_args(argv)

    if args.item:
        row = {
            "item_id": args.item.strip().upper(),
            "catalog_product_id": args.catalog.strip() or None,
            "preco": 0,
            "quantidade_vendida": 0,
            "seller_id": "",
        }
        # tenta preço via products se catalog informado
        if args.catalog and ml_client._enabled():
            try:
                ri = ml_client._request_ml(
                    "GET", f"{BASE}/products/{args.catalog.strip()}/items", timeout=20
                )
                if ri.status_code == 200:
                    for it in (ri.json() or {}).get("results") or []:
                        if str(it.get("item_id") or "").upper() == row["item_id"]:
                            row["preco"] = _f(it.get("price"))
                            row["seller_id"] = str(it.get("seller_id") or "")
                            row["quantidade_vendida"] = _i(it.get("sold_quantity"))
                            break
            except Exception:
                pass
        enriquecido = enriquecer_anuncio(row)
        out = {
            "ok": True,
            "termo": None,
            "total": 1,
            "anuncios": [enriquecido],
            "taxa_estimada_pct": ML_ANALISE_ANUNCIO_TAXA_PCT,
        }
    else:
        out = analisar_por_termo(args.termo, limite=max(1, args.limite))

    path = ROOT / "logs" / "analise_anuncio_concorrente_ultima.json"
    escrever_json_atomico(
        path,
        {"timestamp": datetime.now(timezone.utc).isoformat(), **out},
    )
    msg = montar_mensagem_metricas(out)
    print(msg)
    print(f"\nSnapshot: {path}")
    if args.telegram:
        from core.notificador import alertar_gestor

        alertar_gestor(msg, chave="analise:anuncio:metricas")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
