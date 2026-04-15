"""
agentes/repricing/agente_repricing_marketplaces.py
Monitora produtos nos marketplaces e ajusta preço com lucro mínimo.
"""
from __future__ import annotations

import logging

from core.config import LUCRO_MINIMO_REPRICING_PCT, REPRICING_ABAIXO_CONCORRENTE_PCT
from core.notificador import alertar_gestor
from integracoes.bling.bling_client import listar_produtos, buscar_produto
from integracoes.ml.ml_client import atualizar_preco_item as atualizar_preco_ml
from integracoes.shopee.shopee_client import atualizar_preco_item as atualizar_preco_shopee
from integracoes.magalu.magalu_client import atualizar_preco_item as atualizar_preco_magalu
from integracoes.amazon.amazon_client import atualizar_preco_item as atualizar_preco_amazon

logger = logging.getLogger("agente_repricing_marketplaces")


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _calcular_preco_min_lucro(custo: float, lucro_minimo_pct: float) -> float:
    margem = max(0.0, min(99.0, lucro_minimo_pct)) / 100.0
    return custo / (1 - margem) if custo > 0 else 0.0


def _calcular_novo_preco(preco_atual: float, custo: float, preco_concorrente: float | None, lucro_minimo_pct: float) -> tuple[float, float]:
    preco_min_lucro = _calcular_preco_min_lucro(custo, lucro_minimo_pct)
    alvo_concorrencia = 0.0
    if preco_concorrente and preco_concorrente > 0:
        alvo_concorrencia = preco_concorrente * (1 - REPRICING_ABAIXO_CONCORRENTE_PCT / 100.0)

    base = max(preco_min_lucro, alvo_concorrencia if alvo_concorrencia > 0 else preco_atual)
    novo_preco = round(max(0.01, base), 2)
    margem = ((novo_preco - custo) / novo_preco * 100) if novo_preco > 0 else 0.0
    return novo_preco, margem


def _updater(canal: str):
    return {
        "mercadolivre": atualizar_preco_ml,
        "shopee": atualizar_preco_shopee,
        "magalu": atualizar_preco_magalu,
        "amazon": atualizar_preco_amazon,
    }.get(canal)


def _item_ref(canal: str, canal_data: dict, sku: str):
    if canal == "mercadolivre":
        return canal_data.get("item_id") or sku
    if canal == "shopee":
        return canal_data.get("item_id")
    return canal_data.get("sku") or sku


def executar(produtos: list[dict] | None = None, dry_run: bool = True, lucro_minimo_pct: float | None = None) -> dict:
    lucro_minimo = float(lucro_minimo_pct if lucro_minimo_pct is not None else LUCRO_MINIMO_REPRICING_PCT)
    produtos_base = produtos if produtos is not None else listar_produtos()
    ajustes = []

    for p in produtos_base:
        sku = p.get("sku")
        if not sku:
            continue
        completo = buscar_produto(sku) or {}
        custo = _to_float(p.get("custo", completo.get("custo", 0.0)))
        if custo <= 0:
            continue

        canais = p.get("canais", {}) if isinstance(p.get("canais", {}), dict) else {}
        for canal, dados in canais.items():
            if not isinstance(dados, dict) or not dados.get("ativo", False):
                continue
            preco_atual = _to_float(dados.get("preco", p.get("preco", 0)))
            preco_concorrente = _to_float(dados.get("preco_concorrente", 0), 0)

            novo_preco, margem = _calcular_novo_preco(preco_atual, custo, preco_concorrente, lucro_minimo)
            ajustar = abs(novo_preco - preco_atual) >= 0.05

            resultado_aplicacao = None
            if ajustar and not dry_run:
                ref = _item_ref(canal, dados, sku)
                fn = _updater(canal)
                if fn and ref:
                    resultado_aplicacao = fn(ref, novo_preco)

            ajustes.append(
                {
                    "sku": sku,
                    "canal": canal,
                    "preco_atual": round(preco_atual, 2),
                    "novo_preco": novo_preco,
                    "custo": round(custo, 2),
                    "margem_pct": round(margem, 2),
                    "ajustar": ajustar,
                    "aplicado": resultado_aplicacao,
                    "motivo": f"lucro mínimo {lucro_minimo:.1f}% garantido",
                }
            )

    total_ajustes = sum(1 for a in ajustes if a["ajustar"])
    if total_ajustes > 0:
        alertar_gestor(
            f"Repricing marketplaces: {total_ajustes} ajustes detectados\n"
            f"Modo: {'simulação' if dry_run else 'aplicação'} | lucro mínimo: {lucro_minimo:.1f}%"
        )

    payload = {
        "dry_run": dry_run,
        "lucro_minimo_pct": lucro_minimo,
        "total_itens": len(ajustes),
        "total_ajustes": total_ajustes,
        "ajustes": ajustes,
    }
    logger.info("Repricing marketplaces: %s", payload)
    return payload
