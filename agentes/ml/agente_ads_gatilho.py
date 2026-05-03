"""
agentes/ml/agente_ads_gatilho.py
Decide automaticamente quando ligar, escalar ou pausar Product Ads no ML.
Baseado em avaliações reais, nota média e ACOS atual.
"""
from __future__ import annotations

import logging
from datetime import datetime

from core.notificador import alertar_gestor
from core.config import (
    AVALIACOES_PARA_ADS,
    NOTA_MINIMA_PARA_ADS,
    AVALIACOES_PARA_ESCALAR,
    ACOS_MAXIMO,
    BUDGET_FASE_INICIO,
    BUDGET_FASE_CRESCIMENTO,
    BUDGET_FASE_ESCALA,
)
from integracoes.ml.ml_client import buscar_reputacao_vendedor, buscar_acos_ads

logger = logging.getLogger("agente_ads_gatilho")


def avaliar_momento_ads(
    avaliacoes: int,
    nota_media: float,
    acos_atual: float = 0.0,
    full_ativo: bool = False,
) -> dict:
    decisao = "aguardar"
    budget_sugerido = 0.0
    motivos = []

    if avaliacoes < AVALIACOES_PARA_ADS:
        motivos.append(f"Avaliações insuficientes: {avaliacoes}/{AVALIACOES_PARA_ADS}")
        motivos.append("Focar em orgânico + Programa Decola")

    elif nota_media < NOTA_MINIMA_PARA_ADS:
        motivos.append(f"Nota abaixo do mínimo: {nota_media:.1f}/{NOTA_MINIMA_PARA_ADS}")
        motivos.append("Melhorar atendimento antes de investir em ads")

    elif acos_atual > ACOS_MAXIMO and acos_atual > 0:
        decisao = "pausar"
        budget_sugerido = 0.0
        motivos.append(f"ACOS alto: {acos_atual*100:.0f}% (máx {ACOS_MAXIMO*100:.0f}%)")
        motivos.append("Revisar título e preço antes de religar")

    elif datetime.now().month in (10, 11, 12) and avaliacoes >= AVALIACOES_PARA_ADS and nota_media >= NOTA_MINIMA_PARA_ADS:
        decisao = "escalar"
        budget_sugerido = BUDGET_FASE_ESCALA
        motivos.append("Pico sazonal (Out-Dez) — escalar agressivo")
        motivos.append(f"Budget sugerido: R$ {BUDGET_FASE_ESCALA}/dia")

    elif full_ativo and avaliacoes >= AVALIACOES_PARA_ESCALAR:
        decisao = "escalar"
        budget_sugerido = BUDGET_FASE_CRESCIMENTO
        motivos.append("Full ativo + volume sólido — escalar budget")
        motivos.append(f"Budget sugerido: R$ {BUDGET_FASE_CRESCIMENTO}/dia")

    elif avaliacoes >= AVALIACOES_PARA_ADS:
        decisao = "ligar"
        budget_sugerido = BUDGET_FASE_INICIO
        motivos.append("Avaliações suficientes para iniciar Product Ads")
        motivos.append(f"Budget: R$ {BUDGET_FASE_INICIO}/dia — campanha automática por 2 semanas")

    resultado = {
        "decisao": decisao,
        "budget_sugerido_dia": budget_sugerido,
        "avaliacoes": avaliacoes,
        "nota_media": nota_media,
        "acos_atual": acos_atual,
        "full_ativo": full_ativo,
        "motivos": motivos,
    }

    if decisao == "ligar":
        alertar_gestor(
            f"ADS ML: hora de LIGAR o Product Ads\n"
            f"Budget: R$ {budget_sugerido}/dia\n"
            + "\n".join(motivos)
        )
    elif decisao == "pausar":
        alertar_gestor(
            f"ADS ML: PAUSAR — ACOS {acos_atual*100:.0f}% acima do limite\n"
            + "\n".join(motivos)
        )
    elif decisao == "escalar":
        alertar_gestor(
            f"ADS ML: ESCALAR budget para R$ {budget_sugerido}/dia\n"
            + "\n".join(motivos)
        )

    logger.info("Gatilho ads: %s", resultado)
    return resultado


def executar(item_id: str = "", acos_atual: float = 0.0, full_ativo: bool = False) -> dict:
    rep = buscar_reputacao_vendedor()
    if item_id and acos_atual == 0.0:
        acos_atual = buscar_acos_ads(item_id)
    metrics = rep.get("metrics", {})
    avaliacoes = int(metrics.get("total_ratings", 0))
    nota = float(metrics.get("average_rating", 0.0))
    return avaliar_momento_ads(avaliacoes, nota, acos_atual, full_ativo)


if __name__ == "__main__":
    import pprint
    pprint.pprint(executar())
