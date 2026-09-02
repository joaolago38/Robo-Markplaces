"""Anúncios compactos no contexto Claude (catálogo + snapshot da conta)."""
from __future__ import annotations

import logging
from typing import Any

from core.claude_client import mlb_invalido
from core.claude_ml.numeros import num

logger = logging.getLogger("claude_ml_anuncios")

_LIMITE_PADRAO = 24


def _titulo(v: Any, limite: int = 80) -> str:
    return str(v or "").strip()[:limite]


def compactar_linha(
    *,
    sku: str = "",
    mlb: str = "",
    titulo: str = "",
    preco: Any = None,
    estoque: Any = None,
    status: str = "",
    vendidos: Any = None,
    listing_type: str = "",
    fonte: str = "",
) -> dict[str, Any]:
    mid = str(mlb or "").strip()
    publicado = bool(mid) and not mlb_invalido(mid)
    return {
        "sku": str(sku or "").strip()[:40],
        "mlb": mid[:20] if publicado else (mid[:20] if mid else ""),
        "publicado": publicado,
        "titulo": _titulo(titulo),
        "preco": round(num(preco), 2) if preco is not None and str(preco) != "" else None,
        "estoque": int(num(estoque)) if estoque is not None and str(estoque) != "" else None,
        "status": str(status or "")[:20],
        "vendidos": int(num(vendidos)) if vendidos is not None else None,
        "listing_type": str(listing_type or "")[:24],
        "fonte": fonte,
    }


def _chave(linha: dict[str, Any]) -> str:
    sku = str(linha.get("sku") or "").strip()
    if sku:
        return f"sku:{sku}"
    if linha.get("publicado") and linha.get("mlb"):
        return f"mlb:{linha['mlb']}"
    tit = str(linha.get("titulo") or "").strip().lower()
    return f"tit:{tit}" if tit else ""


def mesclar_linhas(*grupos: list[dict[str, Any]], limite: int = _LIMITE_PADRAO) -> list[dict[str, Any]]:
    por: dict[str, dict[str, Any]] = {}
    ordem: list[str] = []
    for grupo in grupos:
        for raw in grupo or []:
            if not isinstance(raw, dict):
                continue
            k = _chave(raw)
            if not k:
                continue
            if k not in por:
                por[k] = dict(raw)
                ordem.append(k)
                continue
            atual = por[k]
            for campo in ("sku", "mlb", "titulo", "status", "listing_type", "fonte"):
                if not atual.get(campo) and raw.get(campo):
                    atual[campo] = raw[campo]
            for campo in ("preco", "estoque", "vendidos"):
                if atual.get(campo) in (None, "") and raw.get(campo) not in (None, ""):
                    atual[campo] = raw[campo]
            atual["publicado"] = bool(atual.get("publicado") or raw.get("publicado"))
    return [por[k] for k in ordem[: max(1, int(limite))]]


def linhas_catalogo_ml(*, limite: int = _LIMITE_PADRAO) -> list[dict[str, Any]]:
    try:
        from core.catalogo_produtos import carregar_produtos_catalogo

        produtos = carregar_produtos_catalogo()
    except Exception as exc:
        logger.debug("catalogo anuncios Claude: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for p in produtos:
        if not isinstance(p, dict):
            continue
        canais = p.get("canais") if isinstance(p.get("canais"), dict) else {}
        ml = canais.get("mercadolivre") if isinstance(canais.get("mercadolivre"), dict) else {}
        if not ml:
            continue
        out.append(
            compactar_linha(
                sku=str(p.get("sku") or ""),
                mlb=str(ml.get("item_id") or ""),
                titulo=str(ml.get("titulo_anuncio") or p.get("titulo_sugerido_ml") or p.get("nome") or ""),
                preco=ml.get("preco") if ml.get("preco") not in (None, 0, 0.0) else p.get("preco"),
                estoque=ml.get("estoque") if ml.get("estoque") is not None else p.get("estoque_total"),
                status="catalogo",
                fonte="catalogo",
            )
        )
        if len(out) >= limite:
            break
    return out


def linhas_resumo_conta(resumo: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(resumo, dict):
        return []
    amostra = resumo.get("anuncios_amostra")
    if not isinstance(amostra, list):
        return []
    linhas: list[dict[str, Any]] = []
    for a in amostra:
        if not isinstance(a, dict):
            continue
        linhas.append(
            compactar_linha(
                mlb=str(a.get("item_id") or a.get("mlb") or ""),
                titulo=str(a.get("titulo") or ""),
                preco=a.get("preco"),
                vendidos=a.get("vendidos") or a.get("sold_quantity"),
                status=str(a.get("status") or ""),
                listing_type=str(a.get("listing_type_id") or ""),
                fonte="resumo_conta",
            )
        )
    return linhas


def linhas_sem_venda(snap: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(snap, dict):
        return []
    itens = snap.get("itens")
    if not isinstance(itens, list):
        return []
    linhas: list[dict[str, Any]] = []
    for a in itens[:12]:
        if not isinstance(a, dict):
            continue
        linhas.append(
            compactar_linha(
                sku=str(a.get("sku") or ""),
                mlb=str(a.get("item_id") or ""),
                titulo=str(a.get("titulo") or ""),
                preco=a.get("preco"),
                vendidos=a.get("sold_quantity_total") or a.get("vendidos"),
                status=str(a.get("acao") or "sem_venda"),
                fonte="sem_venda",
            )
        )
    return linhas


def linhas_api_ao_vivo(*, limite: int = _LIMITE_PADRAO) -> list[dict[str, Any]]:
    try:
        from integracoes.ml.ml_client import listar_meus_anuncios

        raw = listar_meus_anuncios(statuses=("active", "paused"))
    except Exception as exc:
        logger.debug("listar_meus_anuncios no contexto Claude: %s", exc)
        return []
    linhas: list[dict[str, Any]] = []
    for a in raw or []:
        if not isinstance(a, dict):
            continue
        linhas.append(
            compactar_linha(
                sku=str(a.get("sku") or a.get("seller_custom_field") or ""),
                mlb=str(a.get("item_id") or a.get("id") or ""),
                titulo=str(a.get("titulo") or a.get("title") or ""),
                preco=a.get("preco") or a.get("price"),
                estoque=a.get("estoque") or a.get("available_quantity"),
                vendidos=a.get("sold_quantity") or a.get("vendidos"),
                status=str(a.get("status") or ""),
                listing_type=str(a.get("listing_type_id") or ""),
                fonte="api",
            )
        )
        if len(linhas) >= limite:
            break
    return linhas


def bloco_anuncios_ml(
    *,
    resumo_conta: dict[str, Any] | None = None,
    sem_venda: dict[str, Any] | None = None,
    ao_vivo: bool = False,
    limite: int = _LIMITE_PADRAO,
) -> dict[str, Any]:
    catalogo = linhas_catalogo_ml(limite=limite)
    conta = linhas_resumo_conta(resumo_conta)
    parados = linhas_sem_venda(sem_venda)
    vivo = linhas_api_ao_vivo(limite=limite) if ao_vivo else []
    itens = mesclar_linhas(vivo, conta, parados, catalogo, limite=limite)
    pub = sum(1 for i in itens if i.get("publicado"))
    pend = sum(1 for i in itens if not i.get("publicado"))
    fontes = []
    if vivo:
        fontes.append("api")
    if conta:
        fontes.append("resumo_conta")
    if parados:
        fontes.append("sem_venda")
    if catalogo:
        fontes.append("catalogo")
    return {
        "total": len(itens),
        "publicados": pub,
        "pendente_mlb": pend,
        "fonte": "+".join(fontes) or "vazio",
        "itens": itens,
    }
