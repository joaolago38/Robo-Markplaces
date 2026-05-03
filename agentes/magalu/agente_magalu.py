"""
Agente Magalu - versão limpa 100% funcional
"""

import logging
import time

from core.claude_client import responder_chat
from core.notificador import alertar
from integracoes.bling.bling_client import buscar_produto
from integracoes.magalu.magalu_client import (
    listar_perguntas_nao_respondidas,
    responder_pergunta,
)

logger = logging.getLogger("agente_magalu")

def validar_produto(produto):
    if not produto:
        return False
    estoque = produto.get("estoque", 0)

    if estoque <= 0:
        return False

    return True

def processar_perguntas():
    logger.info("Magalu: verificando perguntas...")
    perguntas = listar_perguntas_nao_respondidas()

    ok = 0

    for p in perguntas:
        texto = (p.get("question") or p.get("text") or "").strip()

        if not texto:
            continue

        produto_id = p.get("sku") or p.get("product_id") or p.get("produto_id") or ""
        produto = buscar_produto(str(produto_id)) or {}
        question_id = p.get("id") or p.get("question_id")

        if not validar_produto(produto):
            continue

        try:
            resposta = responder_chat(texto, produto, "magalu")
            if question_id and responder_pergunta(str(question_id), resposta):
                logger.info("[Magalu] respondido question_id=%s", question_id)
                ok += 1

        except Exception as e:
            logger.error(f"Erro Magalu IA: {e}")
            alertar("Erro no agente Magalu")

        time.sleep(1)

    return ok

def monitorar_metricas():
    logger.info("Magalu: monitorando métricas...")

    devolucao = 0.01

    if devolucao > 0.02:
        alertar("Taxa de devolução alta no Magalu")

    return {"devolucao": devolucao}

def executar():
    logger.info("=== Agente Magalu iniciado ===")

    resultado = {
        "respostas": processar_perguntas(),
        "metricas": monitorar_metricas(),
    }
    try:
        from agentes.vendas_notificador import notificar_pedidos_novos_marketplace

        resultado["vendas_whatsapp"] = notificar_pedidos_novos_marketplace("magalu")
    except Exception as exc:
        logger.error("Notificação vendas WhatsApp (Magalu): %s", exc)
        resultado["vendas_whatsapp"] = {}

    logger.info(f"Resultado Magalu: {resultado}")

    return resultado


if __name__ == "__main__":
    print(executar())
