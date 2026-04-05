"""
Agente Shopee (versão limpa)
"""

"""
Agente Shopee (100% corrigido)
"""

import logging
import time


from core.claude_client import responder_chat
from core.notificador import alertar

logger = logging.getLogger("agente_shopee")

def responder_perguntas():
    logger.info("Shopee: verificando perguntas...")

    perguntas = [
        {"id": 1, "text": "Tem pronta entrega?"},
        {"id": 2, "text": "Qual prazo de envio?"}
    ]

    ok = 0

    for p in perguntas:
        texto = p.get("text", "").strip()

        if not texto:
            continue

        try:
            resposta = responder_chat(texto, {}, "shopee")
            logger.info(f"[Shopee] {texto} -> {resposta}")
            ok += 1

        except Exception as e:
            logger.error(f"Erro Shopee IA: {e}")
            alertar("Erro no agente Shopee")

        time.sleep(1)

    return ok