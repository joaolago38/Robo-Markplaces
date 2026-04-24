"""
agentes/repricing/agente_repricing_impala.py
Repricing consciente de fase para kits Impala.
Estende o repricing existente respeitando margem por fase operacional.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from core.notificador import alertar_gestor

logger = logging.getLogger("agente_repricing_impala")

TAXA_ML = 0.14
CATALOGO_PATH = Path("catalogo/produtos.json")

MARGEM_POR_FASE = {
    1: 0.10,  # Fase 1: aceita 10% para ganhar avaliações
    2: 0.18,  # Fase 2: crescimento
    3: 0.25,  # Fase 3: reputação / Full ativo
}


def _carregar_kits() -> list[dict]:
    try:
        with open(CATALOGO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("catalogo/produtos.json não encontrado")
        return []


def calcular_preco_ideal(kit: dict, fase: int | None = None) -> dict:
    fase = fase or kit.get("fase_atual", 1)
    custo = float(kit.get("custo_total", 0.0))
    margem_min = MARGEM_POR_FASE.get(fase, 0.10)

    if custo <= 0:
        return {"sku": kit.get("sku"), "erro": "custo_total ausente ou zero"}

    # Preço mínimo absoluto para não dar prejuízo
    preco_min_lucro = custo / (1 - TAXA_ML - margem_min)

    # Preço alvo definido para a fase no catálogo
    preco_fase = float(kit.get("precos_por_fase", {}).get(f"fase{fase}", preco_min_lucro))

    # Nunca abaixo do piso de lucro
    preco_sugerido = round(max(preco_fase, preco_min_lucro), 2)

    lucro = preco_sugerido * (1 - TAXA_ML) - custo
    margem_real = lucro / preco_sugerido if preco_sugerido > 0 else 0.0

    preco_atual = float(kit.get("preco", 0.0))
    ajuste_necessario = abs(preco_sugerido - preco_atual) >= 0.50

    return {
        "sku": kit.get("sku"),
        "nome": kit.get("nome"),
        "fase": fase,
        "custo_total": round(custo, 2),
        "preco_atual": round(preco_atual, 2),
        "preco_sugerido": preco_sugerido,
        "lucro_estimado": round(lucro, 2),
        "margem_real_pct": round(margem_real * 100, 1),
        "ajuste_necessario": ajuste_necessario,
        "motivo": f"margem mínima fase {fase}: {margem_min*100:.0f}%",
    }


def executar(dry_run: bool = True, fase_override: int | None = None) -> dict:
    kits = _carregar_kits()
    resultados = [calcular_preco_ideal(k, fase_override) for k in kits]
    ajustes = [r for r in resultados if r.get("ajuste_necessario")]

    if ajustes:
        nomes = ", ".join(r["sku"] for r in ajustes)
        alertar_gestor(
            f"Repricing Impala: {len(ajustes)} kit(s) precisam ajuste\n"
            f"SKUs: {nomes}\n"
            f"Modo: {'simulação' if dry_run else 'aplicação'}"
        )

    payload = {
        "dry_run": dry_run,
        "total_kits": len(resultados),
        "total_ajustes": len(ajustes),
        "ajustes": ajustes,
        "detalhes": resultados,
    }
    logger.info("Repricing Impala: %s", payload)
    return payload


if __name__ == "__main__":
    import pprint
    pprint.pprint(executar(dry_run=True))
