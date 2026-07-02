"""
agentes/painel_item.py
Painel consolidado por anúncio: junta métricas do Mercado Livre
(preço, estoque, visitas, pedidos) com custo do Bling (via SKU) para
calcular vendas/dia, receita bruta e margem — sem depender de nenhum
serviço de terceiro (ex.: LojaHub Analytics).
"""
from __future__ import annotations

import logging

from integracoes.ml import ml_client
from integracoes.bling.bling_client import buscar_produto

logger = logging.getLogger("painel_item")


def _mapear_sku_por_item_id(item_id: str) -> str | None:
    """
    Não há endpoint do ML que devolva o SKU de um único item_id
    isoladamente com baixo custo, então reaproveita a listagem
    completa de anúncios ativos e faz o casamento em memória.
    Retorna None se o item não estiver entre os anúncios ativos do
    vendedor (ex.: item pausado/encerrado) ou se o SKU não estiver
    cadastrado no Mercado Livre.
    """
    try:
        for anuncio in ml_client.listar_meus_anuncios():
            if anuncio.get("item_id") == item_id:
                sku = (anuncio.get("sku") or "").strip()
                return sku or None
        return None
    except Exception as exc:
        logger.error("painel_item mapear_sku erro item_id=%s: %s", item_id, exc)
        return None


def _somar_vendas_do_item(item_id: str, dias: int) -> dict:
    """
    Percorre os pedidos pagos dos últimos `dias` e soma quantidade e
    receita bruta apenas das linhas que batem com este item_id.
    Retorna sempre um dict com os totais, mesmo em caso de falha na
    chamada de pedidos (fica tudo zerado e `pedidos_ok=False`).
    """
    pedidos, ok = ml_client.listar_pedidos_detalhado(dias=dias)
    unidades = 0
    receita_bruta = 0.0
    for pedido in pedidos:
        for item in pedido.get("itens", []):
            if str(item.get("item_id", "")) != item_id:
                continue
            qtd = int(item.get("quantidade", 0) or 0)
            preco_unit = float(item.get("preco_unitario", 0) or 0)
            unidades += qtd
            receita_bruta += qtd * preco_unit
    return {
        "unidades_vendidas": unidades,
        "receita_bruta": round(receita_bruta, 2),
        "pedidos_ok": ok,
    }


def montar_painel_item(item_id: str, dias: int = 7) -> dict:
    """
    Painel consolidado de um anúncio específico, equivalente ao que a
    extensão LojaHub Analytics mostra na página do Mercado Livre —
    exceto "Vendas Catálogo" (métrica agregada de todos os vendedores
    do catálogo, que a API pública do ML não expõe).

    Retorna sempre um dict, mesmo quando alguma fonte falha — os
    campos da fonte indisponível vêm com valor 0/None e a flag
    correspondente (`metricas_ok`, `pedidos_ok`, `custo_ok`) fica
    False, para quem consumir saber diferenciar "zero de verdade" de
    "não consegui buscar". Nunca lança exceção.
    """
    item_id = (item_id or "").strip()
    if not item_id:
        return {"item_id": item_id, "erro": "item_id vazio"}

    metricas = ml_client.buscar_metricas_item(item_id) or {}
    metricas_ok = bool(metricas)

    vendas = _somar_vendas_do_item(item_id, dias)

    sku = _mapear_sku_por_item_id(item_id)
    custo_unit = 0.0
    custo_ok = False
    if sku:
        produto_bling = buscar_produto(sku)
        if produto_bling:
            custo_unit = float(produto_bling.get("custo", 0) or 0)
            custo_ok = True

    preco = float(metricas.get("preco", 0) or 0)
    unidades = vendas["unidades_vendidas"]
    receita_bruta = vendas["receita_bruta"]
    custo_total = round(custo_unit * unidades, 2)
    receita_liquida_total = round(receita_bruta - custo_total, 2)
    receita_liquida_unitaria = (
        round(preco - custo_unit, 2) if custo_ok else None
    )

    return {
        "item_id": item_id,
        "sku": sku,
        "titulo": metricas.get("titulo", ""),
        "status": metricas.get("status", ""),
        "preco": preco,
        "estoque": metricas.get("estoque"),
        "visitas_7d": metricas.get("visitas_7d"),
        "visitas_30d": metricas.get("visitas_30d"),
        "periodo_vendas_dias": dias,
        "unidades_vendidas": unidades,
        "vendas_por_dia": round(unidades / dias, 2) if dias > 0 else 0.0,
        "receita_bruta_total": receita_bruta,
        "custo_unitario": custo_unit if custo_ok else None,
        "receita_liquida_unitaria": receita_liquida_unitaria,
        "receita_liquida_total": receita_liquida_total if custo_ok else None,
        "metricas_ok": metricas_ok,
        "pedidos_ok": vendas["pedidos_ok"],
        "custo_ok": custo_ok,
    }
