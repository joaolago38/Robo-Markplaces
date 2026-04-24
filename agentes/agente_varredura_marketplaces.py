"""
agentes/agente_varredura_marketplaces.py
Varredura central de marketplaces para detectar atualizações diariamente.
"""
from __future__ import annotations

import logging
from datetime import datetime

from agentes.algoritmo_marketplaces import executar as executar_algoritmo_marketplaces
from agentes.auto_respostas_visuais import executar as executar_auto_respostas_visuais
from agentes.manutencao_marketplaces import executar as executar_manutencao_marketplaces
from agentes.repricing.agente_repricing_marketplaces import executar as executar_repricing_marketplaces
from core.config import SPEC
from integracoes.amazon.amazon_client import listar_mensagens_nao_respondidas
from integracoes.magalu.magalu_client import listar_perguntas_nao_respondidas as listar_magalu
from integracoes.ml.ml_client import listar_perguntas_nao_respondidas as listar_ml
from integracoes.shopee.shopee_client import listar_perguntas_nao_respondidas as listar_shopee

# Lê quais marketplaces estão ativos no spec.yaml uma única vez na inicialização
_MARKETPLACES_ATIVOS: set[str] = {
    m["id"] for m in SPEC.get("marketplaces", []) if m.get("ativo", False)
}

logger = logging.getLogger("agente_varredura_marketplaces")


def coletar_atualizacoes() -> dict:
    """
    Coleta pendências apenas nos marketplaces marcados como ativo: true no spec.yaml.
    """
    atualizacoes: dict[str, int] = {}

    if "mercadolivre" in _MARKETPLACES_ATIVOS:
        try:
            atualizacoes["mercadolivre"] = len(listar_ml() or [])
        except Exception as e:
            logger.warning("Erro ao coletar ML: %s", e)
            atualizacoes["mercadolivre"] = 0

    if "shopee" in _MARKETPLACES_ATIVOS:
        try:
            atualizacoes["shopee"] = len(listar_shopee(page_size=30, max_pages=2) or [])
        except Exception as e:
            logger.warning("Erro ao coletar Shopee: %s", e)
            atualizacoes["shopee"] = 0

    if "magalu" in _MARKETPLACES_ATIVOS:
        try:
            atualizacoes["magalu"] = len(listar_magalu(limit=30) or [])
        except Exception as e:
            logger.warning("Erro ao coletar Magalu: %s", e)
            atualizacoes["magalu"] = 0

    if "amazon" in _MARKETPLACES_ATIVOS:
        try:
            atualizacoes["amazon"] = len(listar_mensagens_nao_respondidas(limit=30) or [])
        except Exception as e:
            logger.warning("Erro ao coletar Amazon: %s", e)
            atualizacoes["amazon"] = 0

    atualizacoes["total"] = sum(atualizacoes.values())
    return atualizacoes


def executar_varredura(
    limite_dias_sem_acesso: int = 5,
    alertar_quando_atencao: bool = False,
    dry_run_repricing: bool = True,
) -> dict:
    """
    Executa uma rodada completa de varredura e ações de rotina.
    """
    atualizacoes = coletar_atualizacoes()
    processou_chat_visual = False
    chat_visual = {"ok": True, "motivo": "sem pendências para responder"}

    if atualizacoes["total"] > 0:
        chat_visual = executar_auto_respostas_visuais()
        processou_chat_visual = True

    resultado = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "atualizacoes": atualizacoes,
        "chat_visual_processado": processou_chat_visual,
        "chat_visual": chat_visual,
        "keepalive": executar_manutencao_marketplaces(limite_dias_sem_acesso=limite_dias_sem_acesso),
        "algoritmo": executar_algoritmo_marketplaces(alertar_quando_atencao=alertar_quando_atencao),
        "repricing": executar_repricing_marketplaces(dry_run=dry_run_repricing),
    }
    logger.info("Varredura marketplaces: %s", resultado)
    return resultado


if __name__ == "__main__":
    print(executar_varredura())
