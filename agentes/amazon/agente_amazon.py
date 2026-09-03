"""
agentes/amazon/agente_amazon.py
Agente da Amazon com integração de mensagens de comprador.
"""
import logging
import time
from datetime import datetime, timezone

from core.atomic_io import escrever_json_atomico
from core.claude_client import responder_chat
from core.config import ROOT, skip_se_spec_inativo
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar
from integracoes.amazon.amazon_client import (
    listar_mensagens_nao_respondidas,
    responder_mensagem,
)
from integracoes.bling.bling_client import buscar_produto

logger = logging.getLogger("agente_amazon")
_TAG = ["marketplace:amazon"]
HEARTBEAT_PATH = ROOT / "logs" / "chat_ultima.json"



def processar_mensagens() -> int:
    mensagens = listar_mensagens_nao_respondidas()
    gauge("chat.fila", float(len(mensagens or [])), tags=_TAG)
    ok = 0
    falhas = 0

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
            else:
                falhas += 1
        except Exception as exc:
            falhas += 1
            logger.error("Erro Amazon IA: %s", exc)
            alertar("Erro no agente Amazon")

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
                "marketplace": "amazon",
                "respondidas": ok,
                "falhas": falhas,
            },
        )
    except Exception as exc:
        logger.warning("Amazon chat heartbeat: %s", exc)

    return ok


def executar() -> dict:
    pulado = skip_se_spec_inativo("amazon")
    if pulado:
        logger.info("Chat Amazon pulado — spec.inativo")
        return pulado
    logger.info("=== Agente Amazon iniciado ===")
    respostas = processar_mensagens()
    vendas_wpp: dict = {}
    try:
        from agentes.vendas_notificador import notificar_pedidos_novos_marketplace

        vendas_wpp = notificar_pedidos_novos_marketplace("amazon")
    except Exception as exc:
        logger.error("Notificação vendas WhatsApp (Amazon): %s", exc)
    return {"respostas": respostas, "vendas_whatsapp": vendas_wpp}
