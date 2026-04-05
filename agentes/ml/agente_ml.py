"""
agentes/ml/agente_ml.py
VERSÃO LIMPA E FUNCIONAL
"""

import logging
import time
import requests

from core.config import ML_ACCESS_TOKEN, ML_SELLER_ID, MARGEM_MINIMA
from core.claude_client import responder_chat
from core.notificador import alertar, alertar_critico
from integracoes.bling.bling_client import buscar_produto

logger = logging.getLogger("agente_ml")
BASE = "https://api.mercadolibre.com"


def _h():
    return {"Authorization": f"Bearer {ML_ACCESS_TOKEN}"}


def pergunta_valida(texto: str) -> bool:
    return bool(texto and len(texto.strip()) >= 3)

def validar_resposta(resposta: str, produto: dict) -> str:
    if not produto:
        return "Vou confirmar os detalhes e já te respondo 😊"

    estoque = produto.get("estoque", 0)

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
    try:
        r = requests.get(
            f"{BASE}/my/received_questions/search",
            headers=_h(),
            params={"status": "UNANSWERED", "seller_id": ML_SELLER_ID},
            timeout=15
        )
        r.raise_for_status()
        return r.json().get("questions", [])

    except Exception as e:
        logger.error(f"ML buscar_perguntas: {e}")
        return []


def responder(pergunta_id, texto):
    try:
        r = requests.post(
            f"{BASE}/answers",
            headers=_h(),
            json={"question_id": pergunta_id, "text": texto},
            timeout=15
        )
        r.raise_for_status()
        return True

    except Exception as e:
        logger.error(f"ML responder {pergunta_id}: {e}")
        return False


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
    try:
        r = requests.get(
            f"{BASE}/users/{ML_SELLER_ID}",
            headers=_h(),
            timeout=15
        )
        r.raise_for_status()

        rep = r.json().get("seller_reputation", {})
        pct = rep.get("metrics", {}).get("claims", {}).get("rate", 0)

        if pct > 0.01:
            alertar_critico(f"Reclamações altas: {pct*100:.1f}%")

        return rep

    except Exception as e:
        logger.error(f"Erro reputação: {e}")
        return {}


def executar():
    logger.info("Agente ML iniciado")

    return {
        "chat": ciclo_chat(),
        "reputacao": verificar_reputacao()
    }
if __name__ == "__main__":
    resultado = executar()
    print(resultado)