"""
agentes/amazon/agente_amazon.py
Agente da Amazon com integração de mensagens de comprador.
"""
import logging
import time

from core.claude_client import responder_chat
from core.notificador import alertar
from integracoes.bling.bling_client import buscar_produto
from integracoes.amazon.amazon_client import (
    listar_mensagens_nao_respondidas,
    responder_mensagem,
)

logger = logging.getLogger("agente_amazon")

def processar_mensagens() -> int:
    mensagens = listar_mensagens_nao_respondidas()
    ok = 0

    for m in mensagens:
        texto = (m.get("message") or m.get("text") or "").strip()
        if not texto:
            continue

        sku = m.get("sku") or m.get("item_id") or ""
        produto = buscar_produto(str(sku)) if sku else {}
        thread_id = m.get("threadId") or m.get("thread_id") or m.get("id")

        try:
            resposta = responder_chat(texto, produto or {}, "amazon")
            if thread_id and responder_mensagem(str(thread_id), resposta):
                ok += 1
        except Exception as exc:
            logger.error("Erro Amazon IA: %s", exc)
            alertar("Erro no agente Amazon")

        time.sleep(1)

    return ok


def executar() -> dict:
    logger.info("=== Agente Amazon iniciado ===")
    respostas = processar_mensagens()
    vendas_wpp: dict = {}
    try:
        from agentes.vendas_notificador import notificar_pedidos_novos_marketplace

        vendas_wpp = notificar_pedidos_novos_marketplace("amazon")
    except Exception as exc:
        logger.error("Notificação vendas WhatsApp (Amazon): %s", exc)
    return {"respostas": respostas, "vendas_whatsapp": vendas_wpp}
