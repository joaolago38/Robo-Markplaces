"""
agentes/ml/agente_ml.py
VERSÃO LIMPA E FUNCIONAL
"""

import logging
import time

from core.config import MARGEM_MINIMA
from core.claude_client import responder_chat
from core.notificador import alertar_critico
from integracoes.bling.bling_client import buscar_produto
from integracoes.ml.ml_client import (
    listar_perguntas_nao_respondidas,
    responder_pergunta,
    buscar_reputacao_vendedor,
)

logger = logging.getLogger("agente_ml")


def pergunta_valida(texto: str) -> bool:
    return bool(texto and len(texto.strip()) >= 3)

def validar_resposta(resposta: str, produto: dict) -> str:
    if not produto:
        return "Vou confirmar os detalhes e já te respondo 😊"

    # Busca estoque real no Bling pelo SKU, evitando depender do catálogo local (pode estar zerado)
    sku = produto.get("sku") or produto.get("codigo") or ""
    if sku:
        produto_bling = buscar_produto(str(sku)) or {}
        estoque = int(produto_bling.get("estoque", produto.get("estoque", 0)) or 0)
    else:
        estoque = int(produto.get("estoque", 0) or 0)

    if estoque <= 0:
        return "Produto indisponível no momento 😊"

    return resposta


def calcular_preco(preco_atual, preco_concorrente, custo):
    try:
        margem = (preco_atual - custo) / preco_atual

        if margem < MARGEM_MINIMA:
            return preco_atual

        return round(preco_concorrente * 1.03, 2)

    except Exception as e:
        logger.error(f"Erro repricing: {e}")
        return preco_atual


def buscar_perguntas():
    return listar_perguntas_nao_respondidas()


def responder(pergunta_id, texto):
    return responder_pergunta(pergunta_id, texto)


def ciclo_chat():
    perguntas = buscar_perguntas()
    ok = 0

    for p in perguntas:
        texto = p.get("text", "").strip()

        if not pergunta_valida(texto):
            continue

        produto = buscar_produto(p.get("item_id", "")) or {}

        try:
            resposta = responder_chat(texto, produto, "mercadolivre")
            resposta = validar_resposta(resposta, produto)

        except Exception as e:
            logger.error(f"Erro IA: {e}")
            resposta = "Já vou te responder melhor 😊"

        if responder(p["id"], resposta):
            ok += 1

        logger.info(f"{texto} -> {resposta}")

        time.sleep(1)

    return ok


def verificar_reputacao():
    rep = buscar_reputacao_vendedor()
    pct = rep.get("metrics", {}).get("claims", {}).get("rate", 0)
    if pct > 0.01:
        alertar_critico(f"Reclamações altas: {pct*100:.1f}%")
    return rep


def executar():
    logger.info("Agente ML iniciado")

    return {
        "chat": ciclo_chat(),
        "reputacao": verificar_reputacao()
    }
if __name__ == "__main__":
    resultado = executar()
    print(resultado)