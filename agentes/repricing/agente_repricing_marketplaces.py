"""
agentes/repricing/agente_repricing_marketplaces.py
Monitora produtos nos marketplaces e ajusta preço com lucro mínimo.
"""
from __future__ import annotations

import logging

from core.config import (
    LUCRO_MINIMO_REPRICING_PCT,
    REPRICING_ABAIXO_CONCORRENTE_PCT,
    MARGEM_FASE_1_PCT,
    MARGEM_FASE_2_PCT,
    MARGEM_FASE_3_PCT,
    TAXA_CANAL_PADRAO_PCT,
    REPRICING_DIFERENCA_MINIMA,
)
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


def _margem_minima_por_fase(fase_atual: int | str | None) -> float:
    fase = str(fase_atual or "1").strip()
    if fase == "2":
        return MARGEM_FASE_2_PCT
    if fase == "3":
        return MARGEM_FASE_3_PCT
    return MARGEM_FASE_1_PCT


def _calcular_preco_piso(custo: float, taxa_canal_pct: float, margem_minima_pct: float) -> float:
    taxa = max(0.0, min(99.0, taxa_canal_pct)) / 100.0
    margem = max(0.0, min(99.0, margem_minima_pct)) / 100.0
    denominador = 1 - taxa - margem
    if custo <= 0 or denominador <= 0:
        return 0.0
    return custo / denominador


def _faixa_bloqueada(nome: str, preco: float) -> str | None:
    nome_lower = (nome or "").lower()
    if ("kit 3" in nome_lower or "kit 4" in nome_lower or "kit 5" in nome_lower) and preco < 22:
        return "kit 3-5 abaixo de R$22 bloqueado"
    if ("kit 10" in nome_lower or "kit 12" in nome_lower) and preco < 38:
        return "kit 10-12 abaixo de R$38 bloqueado"
    if "alicate" in nome_lower and "kit" in nome_lower and preco < 55:
        return "bundle alicate+esmalte abaixo de R$55 bloqueado"
    return None


def _calcular_novo_preco(
    preco_atual: float,
    custo: float,
    preco_concorrente: float | None,
    margem_minima_pct: float,
    taxa_canal_pct: float,
) -> tuple[float, float, float]:
    preco_piso = _calcular_preco_piso(custo, taxa_canal_pct, margem_minima_pct)
    alvo_concorrencia = 0.0
    if preco_concorrente and preco_concorrente > 0:
        alvo_concorrencia = preco_concorrente * (1 - REPRICING_ABAIXO_CONCORRENTE_PCT / 100.0)

    base = max(preco_piso, alvo_concorrencia if alvo_concorrencia > 0 else preco_atual, custo)
    novo_preco = round(max(0.01, base), 2)
    margem = ((novo_preco - custo) / novo_preco * 100) if novo_preco > 0 else 0.0
    return novo_preco, margem, round(preco_piso, 2)


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
        nome = p.get("nome") or completo.get("nome") or sku
        fase_atual = p.get("fase_atual", completo.get("fase_atual", 1))
        margem_fase = _margem_minima_por_fase(fase_atual)
        margem_minima = max(lucro_minimo, margem_fase)

        canais = p.get("canais", {}) if isinstance(p.get("canais", {}), dict) else {}
        for canal, dados in canais.items():
            if not isinstance(dados, dict) or not dados.get("ativo", False):
                continue
            preco_atual = _to_float(dados.get("preco", p.get("preco", 0)))
            preco_concorrente = _to_float(dados.get("preco_concorrente", 0), 0)
            taxa_canal = _to_float(dados.get("taxa_canal_pct", TAXA_CANAL_PADRAO_PCT), TAXA_CANAL_PADRAO_PCT)

            novo_preco, margem, preco_piso = _calcular_novo_preco(
                preco_atual=preco_atual,
                custo=custo,
                preco_concorrente=preco_concorrente,
                margem_minima_pct=margem_minima,
                taxa_canal_pct=taxa_canal,
            )
            bloqueio = _faixa_bloqueada(nome, novo_preco)
            ajustar = abs(novo_preco - preco_atual) >= REPRICING_DIFERENCA_MINIMA and not bloqueio

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
                    "preco_piso": preco_piso,
                    "custo": round(custo, 2),
                    "fase_atual": str(fase_atual),
                    "taxa_canal_pct": round(taxa_canal, 2),
                    "margem_pct": round(margem, 2),
                    "ajustar": ajustar,
                    "aplicado": resultado_aplicacao,
                    "motivo": bloqueio or f"piso por fase {margem_minima:.1f}% + taxa canal {taxa_canal:.1f}%",
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
