"""
agentes/ml/agente_ads_gatilho.py
Decide automaticamente quando ligar, escalar ou pausar Product Ads no ML.
Baseado em avaliações reais, nota média e ACOS atual.
"""
from __future__ import annotations

import logging
from datetime import datetime

from core.notificador import alertar_gestor, perguntar_gestor_e_aguardar
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
        "confirmado_gestor": None,
    }

    if decisao == "ligar":
        pergunta = (
            f"🟢 *ADS ML — LIGAR Product Ads*\n\n"
            f"📊 Avaliações: {avaliacoes} | Nota: {nota_media:.1f}\n"
            f"💰 Budget sugerido: R$ {budget_sugerido:.2f}/dia\n"
            f"📋 Motivo: {motivos[0] if motivos else 'critérios atingidos'}\n\n"
            f"Deseja LIGAR o Product Ads agora?"
        )
        confirmado = perguntar_gestor_e_aguardar(pergunta, timeout_segundos=600)
        resultado["confirmado_gestor"] = confirmado
        if confirmado:
            alertar_gestor(
                f"✅ ADS ML: LIGANDO Product Ads — aprovado pelo gestor\n"
                f"Budget: R$ {budget_sugerido}/dia\n"
                + "\n".join(motivos)
            )
            logger.info("Gestor APROVOU ligar ads — budget R$ %.2f/dia", budget_sugerido)
        else:
            alertar_gestor("⏸ ADS ML: ação de LIGAR cancelada ou sem resposta do gestor.")
            logger.info("Gestor RECUSOU ou não respondeu — ads não ligado")
            resultado["decisao"] = "aguardar"

    elif decisao == "pausar":
        pergunta = (
            f"🔴 *ADS ML — PAUSAR Product Ads*\n\n"
            f"📈 ACOS atual: {acos_atual*100:.0f}% (limite: {ACOS_MAXIMO*100:.0f}%)\n"
            f"📋 Motivo: {motivos[0] if motivos else 'ACOS acima do limite'}\n\n"
            f"Deseja PAUSAR o Product Ads agora?"
        )
        confirmado = perguntar_gestor_e_aguardar(pergunta, timeout_segundos=600)
        resultado["confirmado_gestor"] = confirmado
        if confirmado:
            alertar_gestor(
                f"✅ ADS ML: PAUSANDO — aprovado pelo gestor\n"
                f"ACOS: {acos_atual*100:.0f}%\n"
                + "\n".join(motivos)
            )
            logger.info("Gestor APROVOU pausar ads — ACOS %.0f%%", acos_atual * 100)
        else:
            alertar_gestor("⏸ ADS ML: ação de PAUSAR cancelada ou sem resposta do gestor.")
            logger.info("Gestor RECUSOU ou não respondeu — ads não pausado")
            resultado["decisao"] = "manter"

    elif decisao == "escalar":
        pergunta = (
            f"🚀 *ADS ML — ESCALAR Budget*\n\n"
            f"📊 Avaliações: {avaliacoes} | Full ativo: {'Sim' if full_ativo else 'Não'}\n"
            f"💰 Novo budget sugerido: R$ {budget_sugerido:.2f}/dia\n"
            f"📋 Motivo: {motivos[0] if motivos else 'critérios de escala atingidos'}\n\n"
            f"Deseja ESCALAR o budget de ads agora?"
        )
        confirmado = perguntar_gestor_e_aguardar(pergunta, timeout_segundos=600)
        resultado["confirmado_gestor"] = confirmado
        if confirmado:
            alertar_gestor(
                f"✅ ADS ML: ESCALANDO budget — aprovado pelo gestor\n"
                f"Novo budget: R$ {budget_sugerido}/dia\n"
                + "\n".join(motivos)
            )
            logger.info("Gestor APROVOU escalar ads — budget R$ %.2f/dia", budget_sugerido)
        else:
            alertar_gestor("⏸ ADS ML: ação de ESCALAR cancelada ou sem resposta do gestor.")
            logger.info("Gestor RECUSOU ou não respondeu — budget não escalado")
            resultado["decisao"] = "manter"

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
