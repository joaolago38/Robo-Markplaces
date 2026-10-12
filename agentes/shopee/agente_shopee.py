"""
Agente Shopee (versão limpa)
"""

import logging
import time
from datetime import datetime, timezone

from core.atomic_io import escrever_json_atomico
from core.claude_client import responder_chat
from core.config import ROOT, skip_se_spec_inativo
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar
from integracoes.bling.bling_client import buscar_produto
from integracoes.shopee.shopee_client import (
    listar_perguntas_nao_respondidas,
    responder_pergunta,
)

logger = logging.getLogger("agente_shopee")
_TAG = ["marketplace:shopee"]
HEARTBEAT_PATH = ROOT / "logs" / "chat_ultima.json"


def responder_perguntas():
    logger.info("Shopee: verificando perguntas...")
    perguntas = listar_perguntas_nao_respondidas()
    gauge("chat.fila", float(len(perguntas or [])), tags=_TAG)

    ok = 0
    falhas = 0

    for p in perguntas:
        texto = (p.get("comment") or p.get("text") or "").strip()

        if not texto:
            continue

        item_id = p.get("item_id")
        comment_id = p.get("comment_id") or p.get("id")
        produto = buscar_produto(str(item_id)) if item_id else {}

        try:
            resposta = responder_chat(texto, produto or {}, "shopee")
            if item_id and comment_id and responder_pergunta(item_id, comment_id, resposta):
                logger.info("[Shopee] respondido comment_id=%s", comment_id)
                ok += 1
            else:
                falhas += 1

        except Exception as e:
            falhas += 1
            logger.error(f"Erro Shopee IA: {e}")
            alertar("Erro no agente Shopee")

        time.sleep(1)

    if ok:
        incrementar("chat.respondidas", float(ok), tags=_TAG)
    if falhas:
        incrementar("chat.falha", float(falhas), tags=_TAG)
    incrementar("chat.rodadas", tags=_TAG)
    try:
        escrever_json_atomico(
            HEARTBEAT_PATH,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": falhas == 0,
                "marketplace": "shopee",
                "respondidas": ok,
                "falhas": falhas,
            },
        )
    except Exception as exc:
        logger.warning("Shopee chat heartbeat: %s", exc)

    return ok


def executar() -> dict:
    pulado = skip_se_spec_inativo("shopee")
    if pulado:
        logger.info("Chat Shopee pulado — spec.inativo")
        return pulado
    respostas = responder_perguntas()
    vendas_wpp: dict = {}
    try:
        from agentes.vendas_notificador import notificar_pedidos_novos_marketplace

        vendas_wpp = notificar_pedidos_novos_marketplace("shopee")
    except Exception as exc:
        logger.error("Notificação vendas WhatsApp (Shopee): %s", exc)
    return {"respostas": respostas, "vendas_whatsapp": vendas_wpp}
