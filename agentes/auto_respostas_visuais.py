"""
agentes/auto_respostas_visuais.py
Lê perguntas dos marketplaces e responde automaticamente com contexto visual do produto.
"""
from __future__ import annotations

import logging
import time

from core.claude_client import perguntar
from core.config import SPEC
from core.notificador import alertar_gestor
from integracoes.amazon.amazon_client import listar_mensagens_nao_respondidas as listar_amazon, responder_mensagem as responder_amazon
from integracoes.bling.bling_client import buscar_produto
from integracoes.magalu.magalu_client import listar_perguntas_nao_respondidas as listar_magalu, responder_pergunta as responder_magalu
from integracoes.ml.ml_client import listar_perguntas_nao_respondidas, responder_pergunta as responder_ml
from integracoes.shopee.shopee_client import listar_perguntas_nao_respondidas as listar_shopee, responder_pergunta as responder_shopee

# Marketplaces ativos conforme spec.yaml — evita chamadas desnecessárias
_CANAIS_ATIVOS: set[str] = {
    m["id"] for m in SPEC.get("marketplaces", []) if m.get("ativo", False)
}

logger = logging.getLogger("auto_respostas_visuais")


def _gerar_resposta_visual(pergunta: str, produto: dict, canal: str) -> str:
    imagens = produto.get("imagens", [])
    fotos_ctx = ", ".join(str(i) for i in imagens[:3]) if imagens else "sem fotos disponíveis"
    prompt = f"""
Responda como especialista em marketplace para manicures.
Canal: {canal}
Pergunta do cliente: {pergunta}
Produto: {produto.get('nome', 'N/D')}
Preço: R$ {float(produto.get('preco', 0) or 0):.2f}
Estoque: {produto.get('estoque', 0)}
Descrição: {produto.get('descricao', '')}
Fotos publicadas do produto: {fotos_ctx}

Use as fotos como contexto para descrever cor/acabamento/kit quando aplicável.
Se não houver certeza, diga que confirma detalhes visuais sem inventar.
Resposta objetiva em até 3 frases.
"""
    return perguntar(prompt, max_tokens=220)


def _processar_ml() -> dict:
    perguntas = listar_perguntas_nao_respondidas()
    ok = 0
    for p in perguntas:
        texto = (p.get("text") or "").strip()
        if not texto:
            continue
        item_id = p.get("item_id") or ""
        produto = buscar_produto(str(item_id)) or {}
        resposta = _gerar_resposta_visual(texto, produto, "mercadolivre")
        if responder_ml(p.get("id"), resposta):
            ok += 1
        time.sleep(0.4)
    return {"canal": "mercadolivre", "lidas": len(perguntas), "respondidas": ok}


def _processar_shopee() -> dict:
    perguntas = listar_shopee(page_size=30)
    ok = 0
    for p in perguntas:
        texto = (p.get("comment") or p.get("text") or "").strip()
        item_id = p.get("item_id")
        comment_id = p.get("comment_id") or p.get("id")
        if not texto or not item_id or not comment_id:
            continue
        produto = buscar_produto(str(item_id)) or {}
        resposta = _gerar_resposta_visual(texto, produto, "shopee")
        if responder_shopee(int(item_id), int(comment_id), resposta):
            ok += 1
        time.sleep(0.4)
    return {"canal": "shopee", "lidas": len(perguntas), "respondidas": ok}


def _processar_magalu() -> dict:
    perguntas = listar_magalu(limit=30)
    ok = 0
    for p in perguntas:
        texto = (p.get("question") or p.get("text") or "").strip()
        question_id = p.get("id") or p.get("question_id")
        sku = p.get("sku") or p.get("product_id") or p.get("produto_id") or ""
        if not texto or not question_id:
            continue
        produto = buscar_produto(str(sku)) or {}
        resposta = _gerar_resposta_visual(texto, produto, "magalu")
        if responder_magalu(str(question_id), resposta):
            ok += 1
        time.sleep(0.4)
    return {"canal": "magalu", "lidas": len(perguntas), "respondidas": ok}


def _processar_amazon() -> dict:
    mensagens = listar_amazon(limit=30)
    ok = 0
    for m in mensagens:
        texto = (m.get("message") or m.get("text") or "").strip()
        thread_id = m.get("threadId") or m.get("thread_id") or m.get("id")
        sku = m.get("sku") or m.get("item_id") or ""
        if not texto or not thread_id:
            continue
        produto = buscar_produto(str(sku)) or {}
        resposta = _gerar_resposta_visual(texto, produto, "amazon")
        if responder_amazon(str(thread_id), resposta):
            ok += 1
        time.sleep(0.4)
    return {"canal": "amazon", "lidas": len(mensagens), "respondidas": ok}


def executar() -> dict:
    resultados = []

    if "mercadolivre" in _CANAIS_ATIVOS:
        resultados.append(_processar_ml())
    if "shopee" in _CANAIS_ATIVOS:
        resultados.append(_processar_shopee())
    if "magalu" in _CANAIS_ATIVOS:
        resultados.append(_processar_magalu())
    if "amazon" in _CANAIS_ATIVOS:
        resultados.append(_processar_amazon())

    total_lidas = sum(r["lidas"] for r in resultados)
    total_respondidas = sum(r["respondidas"] for r in resultados)
    payload = {"resultados": resultados, "total_lidas": total_lidas, "total_respondidas": total_respondidas}
    logger.info("Auto respostas visuais: %s", payload)
    if total_lidas > 0:
        alertar_gestor(f"Respostas visuais marketplaces: {total_respondidas}/{total_lidas} respondidas.")
    return payload


if __name__ == "__main__":
    print(executar())
