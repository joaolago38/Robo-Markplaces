"""
agentes/social/agente_metricas_meta.py
Valida campanhas Meta (Instagram/Facebook) e gera alertas/recomendações.
"""
import logging

from core.config import (
    META_CPC_MAXIMO,
    META_CTR_MINIMO,
    META_ROAS_MINIMO,
    META_FREQ_MAXIMA,
    META_GASTO_MINIMO_ALERTA,
)
from core.notificador import alertar_gestor
from integracoes.meta.meta_ads_client import listar_metricas_campanhas, normalizar_metrica_campanha

logger = logging.getLogger("agente_metricas_meta")


def _avaliar_campanha(c: dict) -> dict:
    score = 100
    motivos = []
    recomendacoes = []

    if c["cpc"] > META_CPC_MAXIMO:
        score -= 20
        motivos.append(f"CPC alto ({c['cpc']:.2f})")
        recomendacoes.append("Revisar segmentação e criativos para reduzir CPC.")
    if c["ctr"] < META_CTR_MINIMO:
        score -= 25
        motivos.append(f"CTR baixo ({c['ctr']:.2f}%)")
        recomendacoes.append("Testar novos criativos e chamadas para ação.")
    if c["roas"] < META_ROAS_MINIMO and c["gasto"] >= META_GASTO_MINIMO_ALERTA:
        score -= 30
        motivos.append(f"ROAS baixo ({c['roas']:.2f}) com gasto relevante")
        recomendacoes.append("Ajustar público, oferta e página de destino.")
    if c["frequencia"] > META_FREQ_MAXIMA:
        score -= 15
        motivos.append(f"Frequência alta ({c['frequencia']:.2f})")
        recomendacoes.append("Rotacionar criativos para reduzir fadiga do anúncio.")

    score = max(0, score)
    if score < 60:
        status = "critico"
    elif score < 80:
        status = "atencao"
    else:
        status = "saudavel"

    if not recomendacoes:
        recomendacoes.append("Manter campanha e monitorar próximas 24h.")

    return {
        "id": c["id"],
        "nome": c["nome"],
        "status": status,
        "score": score,
        "motivos": motivos,
        "recomendacoes": recomendacoes[:3],
        "metricas": c,
    }


def executar(alertar_quando_atencao: bool = False, periodo_dias: int = 1) -> dict:
    rows = listar_metricas_campanhas(periodo_dias=periodo_dias)
    campanhas = [_avaliar_campanha(normalizar_metrica_campanha(row)) for row in rows]

    for c in campanhas:
        if c["status"] == "critico" or (alertar_quando_atencao and c["status"] == "atencao"):
            alertar_gestor(
                f"Meta Ads {c['status'].upper()}: {c['nome']} (score {c['score']})\n"
                f"Motivos: {'; '.join(c['motivos'][:2])}\n"
                f"Ação: {'; '.join(c['recomendacoes'][:2])}"
            )

    resumo = {
        "total": len(campanhas),
        "saudavel": sum(1 for c in campanhas if c["status"] == "saudavel"),
        "atencao": sum(1 for c in campanhas if c["status"] == "atencao"),
        "critico": sum(1 for c in campanhas if c["status"] == "critico"),
    }
    payload = {"resumo": resumo, "campanhas": campanhas}
    logger.info("Métricas Meta: %s", payload)
    return payload


if __name__ == "__main__":
    print(executar(alertar_quando_atencao=False, periodo_dias=1))
