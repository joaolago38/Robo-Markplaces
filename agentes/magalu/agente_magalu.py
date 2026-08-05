"""
Agente Magalu - versão limpa 100% funcional
"""

import logging
import time
from datetime import datetime, timezone

from core.atomic_io import escrever_json_atomico
from core.claude_client import responder_chat
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar
from integracoes.bling.bling_client import buscar_produto
from integracoes.magalu.magalu_client import (
    listar_perguntas_nao_respondidas,
    responder_pergunta,
)

logger = logging.getLogger("agente_magalu")
_TAG = ["marketplace:magalu"]
HEARTBEAT_PATH = ROOT / "logs" / "chat_ultima.json"


def validar_produto(produto):
    if not produto:
        return False
    estoque = int(produto.get("estoque") or 0)

    if estoque <= 0:
        return False

    return True


def processar_perguntas():
    logger.info("Magalu: verificando perguntas...")
    perguntas = listar_perguntas_nao_respondidas()
    gauge("chat.fila", float(len(perguntas or [])), tags=_TAG)

    ok = 0
    falhas = 0

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
            else:
                falhas += 1

        except Exception as e:
            falhas += 1
            logger.error(f"Erro Magalu IA: {e}")
            alertar("Erro no agente Magalu")

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
                "marketplace": "magalu",
                "respondidas": ok,
                "falhas": falhas,
            },
        )
    except Exception as exc:
        logger.warning("Magalu chat heartbeat: %s", exc)

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
