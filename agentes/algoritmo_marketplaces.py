"""
agentes/algoritmo_marketplaces.py
Monitora saúde das contas, emite eventos tipados e alerta o gestor.

Canais inativos no spec ou sem credenciais → status "inativo":
não disparam Telegram nem eventos de congelar/priorizar.
"""
import logging

from core.algoritmo_eventos import emitir_de_avaliacao, persistir_eventos
from core.marketplace_algorithm import avaliar_marketplace
from core.marketplace_cnpj import identificar_cnpj_conectado, linha_cnpj_telegram
from core.marketplace_toggle import canal_em_operacao
from core.notificador import alertar_gestor
from integracoes.amazon.amazon_client import obter_saude_conta as saude_amazon
from integracoes.magalu.magalu_client import obter_saude_conta as saude_magalu
from integracoes.ml.ml_client import obter_saude_conta as saude_ml
from integracoes.shopee.shopee_client import obter_saude_conta as saude_shopee

logger = logging.getLogger("algoritmo_marketplaces")

_COLETORES = {
    "mercadolivre": saude_ml,
    "shopee": saude_shopee,
    "magalu": saude_magalu,
    "amazon": saude_amazon,
}


def _marketplaces_a_avaliar() -> list[str]:
    """Spec ativo OU toggle de operação. Ordem estável."""
    ordem = ("mercadolivre", "shopee", "magalu", "amazon")
    return [n for n in ordem if n in _COLETORES and canal_em_operacao(n)]


def executar(alertar_quando_atencao: bool = False) -> dict:
    nomes = _marketplaces_a_avaliar()
    saude = {nome: _COLETORES[nome]() for nome in nomes}
    avaliacoes = {nome: avaliar_marketplace(nome, metrics) for nome, metrics in saude.items()}
    for nome, avaliacao in avaliacoes.items():
        metrics = saude.get(nome) or {}
        ident = identificar_cnpj_conectado(nome, metrics.get("conta_id"))
        avaliacao["cnpj_conectado"] = ident

    # Eventos só para canais configurados (emitir_de_avaliacao também ignora inativo).
    eventos = emitir_de_avaliacao(avaliacoes)
    eventos_ativos = persistir_eventos(eventos, avaliacoes=avaliacoes)

    for nome, avaliacao in avaliacoes.items():
        status = avaliacao["status"]
        if status == "inativo":
            logger.info(
                "Algoritmo %s: inativo/não configurado — sem alerta Telegram",
                nome,
            )
            continue
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
                f"{linha_cnpj_telegram(avaliacao.get('cnpj_conectado') or {})}\n"
                f"Ajustes: {'; '.join(avaliacao['acoes_recomendadas'][:3])}"
                f"{bloco_variacoes}{bloco_ev}",
                chave=f"saude:{nome}:{status}",
                agente_id="algoritmo",
            )

    resumo = {
        "saudavel": sum(1 for a in avaliacoes.values() if a["status"] == "saudavel"),
        "atencao": sum(1 for a in avaliacoes.values() if a["status"] == "atencao"),
        "critico": sum(1 for a in avaliacoes.values() if a["status"] == "critico"),
        "inativo": sum(1 for a in avaliacoes.values() if a["status"] == "inativo"),
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
