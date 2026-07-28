"""
agentes/ml/agente_ml.py
Chat ML + reputação. Dono único das respostas ML no ciclo 30min.
Usa snapshot conversão (Ads/oferta) e mapeia MLB→SKU via catálogo.
"""

import logging
import time

from core.chat_claim import tentar_claim
from core.claude_client import responder_chat
from core.config import MARGEM_MINIMA
from core.contexto_fechamento_ml import carregar_contexto_fechamento_ml
from core.notificador import alertar_critico
from core.produto_lookup import buscar_produto_por_ref
from integracoes.bling.bling_client import buscar_produto
from integracoes.ml.ml_client import (
    ativar_anuncio,
    buscar_reputacao_vendedor,
    encerrar_anuncio,
    listar_perguntas_nao_respondidas,
    pausar_anuncio,
    responder_pergunta,
)

logger = logging.getLogger("agente_ml")


def pergunta_valida(texto: str) -> bool:
    return bool(texto and len(texto.strip()) >= 3)


def validar_resposta(resposta: str, produto: dict) -> str:
    if not produto:
        return "Vou confirmar os detalhes e já te respondo 😊"

    sku = produto.get("sku") or produto.get("codigo") or ""
    if sku and produto.get("_fonte") != "catalogo_local":
        produto_bling = buscar_produto(str(sku)) or {}
        estoque = int(produto_bling.get("estoque", produto.get("estoque", 0)) or 0)
    else:
        estoque = int(produto.get("estoque", 0) or 0)

    if estoque <= 0 and produto.get("_fonte") not in (
        "oferta_conversao_snapshot",
        "catalogo_local",
    ):
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


def _montar_produto_resposta(p: dict, ctx_fechamento: dict) -> dict:
    """Produto via MLB→SKU→Bling; se falhar, oferta do snapshot (sem inventar estoque)."""
    item_id = str(p.get("item_id") or "")
    produto = buscar_produto_por_ref(item_id, canal="mercadolivre") or {}
    if produto:
        return produto

    oferta = ctx_fechamento.get("oferta") or {}
    if not oferta:
        return {}
    # Contexto de copy apenas — estoque desconhecido (não declara disponível)
    return {
        "nome": oferta.get("campanha_nome") or "Kit esmaltes Impala",
        "sku": oferta.get("sku") or "",
        "preco": float(oferta.get("preco_brl") or 0),
        "estoque": 0,
        "descricao": "Kit Impala — oferta ativa na captação Meta→ML (estoque a confirmar)",
        "_fonte": "oferta_conversao_snapshot",
    }


def ciclo_chat():
    perguntas = buscar_perguntas()
    ok = 0
    ctx_f = carregar_contexto_fechamento_ml()
    sinal_ads = ctx_f.get("sinal_ads")
    oferta = ctx_f.get("oferta")
    link_oferta = str(ctx_f.get("link_ml") or "")
    link_ok = bool(ctx_f.get("link_valido"))

    for p in perguntas:
        texto = p.get("text", "").strip()
        pid = str(p.get("id") or "")

        if not pergunta_valida(texto):
            continue

        if not tentar_claim("mercadolivre", pid, agente="chat_ml"):
            logger.info("Pergunta %s já claimed por outro agente — skip", pid)
            continue

        produto = _montar_produto_resposta(p, ctx_f)

        try:
            from integracoes.social.conversao_manicures import (
                pergunta_parece_manicure,
                resposta_chat_ml_haiku,
            )

            if pergunta_parece_manicure(texto) and link_ok and link_oferta:
                resposta = resposta_chat_ml_haiku(
                    texto,
                    link_oferta,
                    produto_ctx=str(
                        (oferta or {}).get("campanha_nome")
                        or produto.get("nome")
                        or "kit Impala"
                    ),
                    sinal_ads=sinal_ads if isinstance(sinal_ads, dict) else None,
                )
                if not resposta:
                    resposta = responder_chat(
                        texto,
                        produto,
                        "mercadolivre",
                        sinal_ads=sinal_ads if isinstance(sinal_ads, dict) else None,
                        oferta_ctx=oferta if isinstance(oferta, dict) else None,
                    )
            else:
                resposta = responder_chat(
                    texto,
                    produto,
                    "mercadolivre",
                    sinal_ads=sinal_ads if isinstance(sinal_ads, dict) else None,
                    oferta_ctx=oferta if isinstance(oferta, dict) else None,
                )
            if produto.get("_fonte") != "oferta_conversao_snapshot":
                resposta = validar_resposta(resposta, produto)

        except Exception as e:
            logger.error(f"Erro IA: {e}")
            resposta = "Já vou te responder melhor 😊"

        if responder(p["id"], resposta):
            ok += 1

        logger.info(
            "%s -> %s | contexto_ads=%s oferta=%s",
            texto,
            resposta,
            bool(sinal_ads),
            (oferta or {}).get("campanha_id"),
        )

        time.sleep(1)

    return ok


def verificar_reputacao():
    rep = buscar_reputacao_vendedor()
    pct = rep.get("metrics", {}).get("claims", {}).get("rate", 0)
    if pct > 0.01:
        alertar_critico(f"Reclamações altas: {pct*100:.1f}%")
    return rep


def gerenciar_status_anuncio(
    item_id: str,
    acao: str,
    *,
    dry_run: bool = True,
    confirmar: bool = False,
) -> dict:
    """
    Pausa, ativa ou encerra um anúncio no ML.
    acao: 'pausar' | 'ativar' | 'encerrar'
    Por padrão dry_run=True (só simula). confirmar=True obrigatório para gravar.
    """
    acoes = {
        "pausar": pausar_anuncio,
        "ativar": ativar_anuncio,
        "encerrar": encerrar_anuncio,
    }
    fn = acoes.get((acao or "").strip().lower())
    if not fn:
        return {"ok": False, "erro": f"ação inválida: {acao!r} (use pausar/ativar/encerrar)"}
    return fn(item_id, dry_run=dry_run, confirmar=confirmar)


def executar():
    logger.info("Agente ML iniciado")

    ctx = carregar_contexto_fechamento_ml()
    out = {
        "chat": ciclo_chat(),
        "reputacao": verificar_reputacao(),
        "contexto_fechamento": {
            "ok": ctx.get("ok"),
            "link_valido": ctx.get("link_valido"),
            "sustentabilidade": ctx.get("sustentabilidade"),
        },
    }
    try:
        from agentes.vendas_notificador import notificar_pedidos_novos_marketplace

        out["vendas_whatsapp"] = notificar_pedidos_novos_marketplace("mercadolivre")
    except Exception as exc:
        logger.error("Notificação vendas WhatsApp (ML): %s", exc)
        out["vendas_whatsapp"] = {}
    return out


if __name__ == "__main__":
    resultado = executar()
    print(resultado)
