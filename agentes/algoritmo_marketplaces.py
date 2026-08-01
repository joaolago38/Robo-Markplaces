"""
agentes/algoritmo_marketplaces.py
Monitora saúde das contas, emite eventos tipados e alerta o gestor.
"""
import logging

from core.algoritmo_eventos import emitir_de_avaliacao, persistir_eventos
from core.config import SPEC
from core.marketplace_algorithm import avaliar_marketplace
from core.notificador import alertar_gestor
from integracoes.amazon.amazon_client import obter_saude_conta as saude_amazon
from integracoes.magalu.magalu_client import obter_saude_conta as saude_magalu
from integracoes.ml.ml_client import obter_saude_conta as saude_ml
from integracoes.shopee.shopee_client import obter_saude_conta as saude_shopee

logger = logging.getLogger("algoritmo_marketplaces")

_MARKETPLACES_ATIVOS: set[str] = {
    m["id"] for m in SPEC.get("marketplaces", []) if m.get("ativo", False)
}


def executar(alertar_quando_atencao: bool = False) -> dict:
    saude = {
        "mercadolivre": saude_ml(),
        "shopee": saude_shopee(),
        "amazon": saude_amazon(),
    }
    if "magalu" in _MARKETPLACES_ATIVOS:
        saude["magalu"] = saude_magalu()
    avaliacoes = {nome: avaliar_marketplace(nome, metrics) for nome, metrics in saude.items()}

    eventos = emitir_de_avaliacao(avaliacoes)
    eventos_ativos = persistir_eventos(eventos) if eventos else persistir_eventos([])

    for nome, avaliacao in avaliacoes.items():
        status = avaliacao["status"]
        variacoes = avaliacao.get("variacoes_relevantes", [])
        variacao_critica = any(
            v.get("metrica") == "score" and v.get("variacao_pct", 0) <= -5 for v in variacoes
        )
        if status == "critico" or (alertar_quando_atencao and status == "atencao") or variacao_critica:
            bloco_variacoes = ""
            if variacoes:
                top = ", ".join([f"{v['metrica']} {v['variacao_pct']}%" for v in variacoes[:2]])
                bloco_variacoes = f"\nVariações: {top}"
            ev_mp = [e["tipo"] for e in eventos_ativos if e.get("marketplace") == nome]
            bloco_ev = f"\nEventos: {', '.join(ev_mp)}" if ev_mp else ""
            alertar_gestor(
                f"Saúde {nome}: {status.upper()} (score {avaliacao['score']})\n"
                f"Ajustes: {'; '.join(avaliacao['acoes_recomendadas'][:3])}"
                f"{bloco_variacoes}{bloco_ev}",
                chave=f"saude:{nome}:{status}",
                agente_id="algoritmo",
            )

    resumo = {
        "saudavel": sum(1 for a in avaliacoes.values() if a["status"] == "saudavel"),
        "atencao": sum(1 for a in avaliacoes.values() if a["status"] == "atencao"),
        "critico": sum(1 for a in avaliacoes.values() if a["status"] == "critico"),
    }

    payload = {
        "resumo": resumo,
        "marketplaces": avaliacoes,
        "eventos": eventos_ativos,
    }
    logger.info("Algoritmo marketplaces: %s", {"resumo": resumo, "eventos": len(eventos_ativos)})
    return payload


if __name__ == "__main__":
    print(executar())
