"""
agentes/algoritmo_marketplaces.py
Monitora saúde das contas e define ajustes de algoritmo por marketplace.
"""
import logging

from core.marketplace_algorithm import avaliar_marketplace
from core.notificador import alertar_gestor
from integracoes.ml.ml_client import obter_saude_conta as saude_ml
from integracoes.shopee.shopee_client import obter_saude_conta as saude_shopee
from integracoes.magalu.magalu_client import obter_saude_conta as saude_magalu
from integracoes.amazon.amazon_client import obter_saude_conta as saude_amazon

logger = logging.getLogger("algoritmo_marketplaces")


def executar(alertar_quando_atencao: bool = False) -> dict:
    saude = {
        "mercadolivre": saude_ml(),
        "shopee": saude_shopee(),
        "magalu": saude_magalu(),
        "amazon": saude_amazon(),
    }
    avaliacoes = {nome: avaliar_marketplace(nome, metrics) for nome, metrics in saude.items()}

    for nome, avaliacao in avaliacoes.items():
        status = avaliacao["status"]
        variacoes = avaliacao.get("variacoes_relevantes", [])
        variacao_critica = any(v.get("metrica") == "score" and v.get("variacao_pct", 0) <= -5 for v in variacoes)
        if status == "critico" or (alertar_quando_atencao and status == "atencao") or variacao_critica:
            bloco_variacoes = ""
            if variacoes:
                top = ", ".join([f"{v['metrica']} {v['variacao_pct']}%" for v in variacoes[:2]])
                bloco_variacoes = f"\nVariações: {top}"
            alertar_gestor(
                f"Saúde {nome}: {status.upper()} (score {avaliacao['score']})\n"
                f"Ajustes: {'; '.join(avaliacao['acoes_recomendadas'][:3])}{bloco_variacoes}"
            )

    resumo = {
        "saudavel": sum(1 for a in avaliacoes.values() if a["status"] == "saudavel"),
        "atencao": sum(1 for a in avaliacoes.values() if a["status"] == "atencao"),
        "critico": sum(1 for a in avaliacoes.values() if a["status"] == "critico"),
    }

    payload = {"resumo": resumo, "marketplaces": avaliacoes}
    logger.info("Algoritmo marketplaces: %s", payload)
    return payload


if __name__ == "__main__":
    print(executar())
