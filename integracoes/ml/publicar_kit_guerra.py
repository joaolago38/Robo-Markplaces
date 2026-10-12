"""
Publica (ou tenta publicar) IMP-MIMO-003 e IMP-PERL-004 no Mercado Livre.

Sem fotos (ML_KIT_PICTURE_URLS) o POST /items é recusado — devolve o payload
para publicação manual. Com --executar e token, envia o anúncio e grava o MLB
em catalogo/produtos.json.
"""
from __future__ import annotations

import os
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.catalogo_produtos import CATALOGO_PATH, carregar_produtos_catalogo
from integracoes.esmaltes.crescimento_esmaltes import _mlb_valido
from integracoes.esmaltes.doutrina_guerra_impala import TITULO_MIMO_ML, sku_pode_publicar_agora

SKUS_FRENTE = ("IMP-MIMO-003", "IMP-PERL-004")


def _fotos() -> list[dict[str, str]]:
    raw = (os.getenv("ML_KIT_PICTURE_URLS") or "").strip()
    if not raw:
        return []
    return [{"source": u.strip()} for u in raw.split(",") if u.strip()]


def _fotos_conta_impala() -> list[dict[str, str]]:
    """Reusa fotos de um anúncio Impala já na conta (POST /items exige pictures)."""
    try:
        from integracoes.ml import ml_client
    except Exception:
        return []
    anuncios = ml_client.listar_meus_anuncios(statuses=("active", "paused")) or []
    for a in anuncios:
        titulo = str(a.get("titulo") or "").lower()
        iid = str(a.get("item_id") or "").strip()
        if "impala" not in titulo or not iid:
            continue
        try:
            r = ml_client._request_ml("GET", f"{ml_client.BASE}/items/{iid}", timeout=20)
            if getattr(r, "status_code", 0) != 200:
                continue
            pics = (r.json() or {}).get("pictures") or []
        except Exception:
            continue
        urls = []
        for p in pics:
            if not isinstance(p, dict):
                continue
            u = str(p.get("secure_url") or p.get("url") or "").strip()
            if u:
                urls.append({"source": u})
        if urls:
            return urls
    return []


def montar_payload_item(produto: dict[str, Any], *, sku: str) -> dict[str, Any]:
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    titulo = str(ml.get("titulo_anuncio") or produto.get("titulo_sugerido_ml") or produto.get("nome") or "")
    if sku.upper() == "IMP-MIMO-003":
        titulo = TITULO_MIMO_ML
    qtd = int(produto.get("valida_unidades") or ml.get("estoque") or 10)
    if qtd <= 0:
        qtd = 10
    payload: dict[str, Any] = {
        "title": titulo[:60],
        "category_id": str(ml.get("categoria_ml") or "MLB1430"),
        "price": float(ml.get("preco") or produto.get("preco") or 0),
        "currency_id": "BRL",
        "available_quantity": qtd,
        "buying_mode": "buy_it_now",
        "listing_type_id": "gold_special",
        "condition": "new",
        "seller_custom_field": sku,
        "pictures": _fotos(),
    }
    return payload


def _gravar_mlb(sku: str, item_id: str) -> None:
    produtos = carregar_produtos_catalogo()
    sku_u = sku.upper()
    for p in produtos:
        if str(p.get("sku") or "").upper() != sku_u:
            continue
        ml = dict((p.get("canais") or {}).get("mercadolivre") or {})
        ml["item_id"] = item_id
        p.setdefault("canais", {})["mercadolivre"] = ml
        break
    escrever_json_atomico(CATALOGO_PATH, produtos)


def publicar_sku(sku: str, *, executar: bool = False) -> dict[str, Any]:
    sku_u = sku.strip().upper()
    produtos = {str(p.get("sku") or "").upper(): p for p in carregar_produtos_catalogo()}
    p = produtos.get(sku_u)
    if not p:
        return {"ok": False, "sku": sku_u, "erro": "sku_ausente_catalogo"}
    ml = (p.get("canais") or {}).get("mercadolivre") or {}
    iid = str(ml.get("item_id") or "")
    if _mlb_valido(iid):
        return {"ok": True, "sku": sku_u, "item_id": iid, "acao": "ja_publicado"}

    pode, motivo = sku_pode_publicar_agora(sku_u)
    if not pode:
        return {"ok": False, "sku": sku_u, "erro": motivo}

    payload = montar_payload_item(p, sku=sku_u)
    fotos = payload.get("pictures") or []
    if not fotos and executar:
        fotos = _fotos_conta_impala()
        payload["pictures"] = fotos
    if not payload.get("pictures"):
        return {
            "ok": False,
            "sku": sku_u,
            "erro": "sem_fotos",
            "payload": payload,
            "dica": "Defina ML_KIT_PICTURE_URLS com URLs públicas das fotos do kit",
        }
    if not executar:
        return {"ok": True, "sku": sku_u, "dry_run": True, "payload": payload}

    from integracoes.ml import ml_client

    r = ml_client._request_ml("POST", f"{ml_client.BASE}/items", json=payload, timeout=40)
    status = getattr(r, "status_code", 0)
    corpo = {}
    try:
        corpo = r.json() or {}
    except Exception:
        corpo = {"text": (getattr(r, "text", "") or "")[:400]}
    if status not in (200, 201) or not corpo.get("id"):
        return {"ok": False, "sku": sku_u, "erro": f"http_{status}", "corpo": corpo, "payload": payload}
    item_id = str(corpo["id"])
    _gravar_mlb(sku_u, item_id)
    return {"ok": True, "sku": sku_u, "item_id": item_id, "acao": "publicado"}


def publicar_frente(*, executar: bool = False) -> dict[str, Any]:
    vinculo: dict[str, Any] = {}
    try:
        from scripts.preparar_guerra_impala import tentar_vincular_mlb

        vinculo = tentar_vincular_mlb()
    except Exception as exc:
        vinculo = {"erro": str(exc)}
    resultados = []
    for sku in SKUS_FRENTE:
        resultados.append(publicar_sku(sku, executar=executar))
    ok_pub = all(r.get("ok") for r in resultados if r.get("erro") != "esperar_mimo_no_ar")
    return {"ok": ok_pub, "vinculo": vinculo, "itens": resultados}
