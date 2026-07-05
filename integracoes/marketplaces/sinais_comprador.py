"""
integracoes/marketplaces/sinais_comprador.py
Coleta sinais de comportamento de compra por marketplace/canal.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("sinais_comprador")


def _item_id_valido(valor: Any) -> bool:
    texto = str(valor or "").strip().upper()
    return bool(texto) and "PREENCHER" not in texto


def _menor_concorrente_por_termo(termo: str, *, limite: int = 8) -> dict[str, Any]:
    if not termo.strip():
        return {}
    try:
        from integracoes.ml.ml_client import buscar_concorrentes_por_termo

        concorrentes = buscar_concorrentes_por_termo(termo, limite=limite)
        com_preco = [c for c in concorrentes if float(c.get("preco") or 0) > 0]
        if not com_preco:
            return {}
        lider = max(com_preco, key=lambda c: int(c.get("quantidade_vendida") or 0))
        menor = min(com_preco, key=lambda c: float(c.get("preco") or 0))
        return {
            "menor_preco": float(menor.get("preco") or 0),
            "lider_preco": float(lider.get("preco") or 0),
            "quantidade_vendida_lider": int(lider.get("quantidade_vendida") or 0),
            "lider_titulo": str(lider.get("titulo") or "")[:80],
            "menor_titulo": str(menor.get("titulo") or "")[:80],
        }
    except Exception as exc:
        logger.warning("sinais concorrente termo=%r: %s", termo[:40], exc)
        return {}


def coletar_sinais_mercadolivre(
    canal_data: dict[str, Any],
    *,
    sku: str,
    termo_busca: str = "",
    dias_vendas: int = 7,
) -> dict[str, Any]:
    from integracoes.ml import ml_client

    item_id = str(canal_data.get("item_id") or "").strip()
    sinais: dict[str, Any] = {
        "marketplace": "mercadolivre",
        "configurado": ml_client._enabled(),
        "sku": sku,
    }
    if not ml_client._enabled():
        sinais["motivo"] = "ML não configurado"
        return sinais

    if _item_id_valido(item_id):
        metricas = ml_client.buscar_metricas_item(item_id) or {}
        sugestao = ml_client.buscar_sugestao_preco(item_id) or {}
        sinais.update(
            {
                "item_id": item_id,
                "visitas_7d": int(metricas.get("visitas_7d") or 0),
                "visitas_30d": int(metricas.get("visitas_30d") or 0),
                "preco_listado": float(metricas.get("preco") or 0),
                "estoque": metricas.get("estoque"),
                "preco_sugerido_ml": float(sugestao.get("preco_sugerido") or 0) or None,
                "preco_sugerido_ml_aplicavel": bool(sugestao.get("aplicavel")),
            }
        )
        try:
            from agentes.painel_item import _somar_vendas_do_item

            vendas = _somar_vendas_do_item(item_id, dias_vendas)
            unidades = int(vendas.get("unidades_vendidas") or 0)
            sinais["unidades_vendidas_7d"] = unidades
            sinais["vendas_por_dia"] = round(unidades / max(1, dias_vendas), 2)
        except Exception as exc:
            logger.warning("sinais vendas ML %s: %s", item_id, exc)

        vivo = ml_client.buscar_menor_preco_concorrente(item_id)
        if vivo and float(vivo) > 0:
            sinais["preco_concorrente_vivo"] = float(vivo)

    termo = termo_busca or str(canal_data.get("termo_busca") or "").strip()
    if termo:
        conc = _menor_concorrente_por_termo(termo)
        sinais.update(conc)
        if conc.get("menor_preco") and not sinais.get("preco_concorrente_vivo"):
            sinais["preco_concorrente_vivo"] = conc["menor_preco"]

    return sinais


def coletar_sinais_generico(canal: str, canal_data: dict[str, Any], *, sku: str) -> dict[str, Any]:
    """Shopee/Magalu/Amazon: saúde + termo do catálogo até termos de busca existirem nos clients."""
    sinais: dict[str, Any] = {"marketplace": canal, "sku": sku, "configurado": False}
    termo = str(canal_data.get("termo_busca") or "").strip()
    try:
        if canal == "shopee":
            from integracoes.shopee import shopee_client

            sinais["configurado"] = bool(shopee_client._enabled())
            if shopee_client._enabled():
                sinais["saude"] = shopee_client.obter_saude_conta()
        elif canal == "magalu":
            from integracoes.magalu import magalu_client

            sinais["configurado"] = bool(magalu_client._enabled())
            if magalu_client._enabled():
                sinais["saude"] = magalu_client.obter_saude_conta()
        elif canal == "amazon":
            from integracoes.amazon import amazon_client

            sinais["configurado"] = bool(amazon_client._enabled())
            if amazon_client._enabled():
                sinais["saude"] = amazon_client.obter_saude_conta()
    except Exception as exc:
        logger.warning("sinais saúde %s: %s", canal, exc)
    if termo and canal == "mercadolivre":
        sinais.update(_menor_concorrente_por_termo(termo))
    sinais["termo_busca"] = termo or None
    return sinais


def coletar_sinais(
    canal: str,
    canal_data: dict[str, Any],
    *,
    sku: str,
    termo_busca: str = "",
) -> dict[str, Any]:
    if canal == "mercadolivre":
        return coletar_sinais_mercadolivre(canal_data, sku=sku, termo_busca=termo_busca)
    return coletar_sinais_generico(canal, canal_data, sku=sku)
