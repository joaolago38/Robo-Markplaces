"""
agentes/ml/agente_ml.py
Chat ML + reputação. Usa contexto da conversão (Ads/oferta) quando existir.
Não liga Ads nem publica IG/FB — só responde perguntas (já era o comportamento).
"""

import logging
import time

from core.config import MARGEM_MINIMA
from core.claude_client import responder_chat
from core.contexto_fechamento_ml import carregar_contexto_fechamento_ml
from core.notificador import alertar_critico
from integracoes.bling.bling_client import buscar_produto
from integracoes.ml.ml_client import (
    listar_perguntas_nao_respondidas,
    responder_pergunta,
    buscar_reputacao_vendedor,
    pausar_anuncio,
    ativar_anuncio,
    encerrar_anuncio,
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


def _montar_produto_resposta(p: dict, ctx_fechamento: dict) -> dict:
    """Tenta produto Bling; se vazio, usa dados da oferta ativa (só contexto)."""
    produto = buscar_produto(p.get("item_id", "")) or {}
    if produto:
        return produto
    oferta = ctx_fechamento.get("oferta") or {}
    if not oferta:
        return {}
    return {
        "nome": oferta.get("campanha_nome") or "Kit esmaltes Impala",
        "sku": oferta.get("sku") or "",
        "preco": float(oferta.get("preco_brl") or 0),
        # estoque desconhecido: evita early-return "indisponível" sem dado real
        "estoque": 1,
        "descricao": "Kit Impala para manicures — oferta ativa na captação Meta→ML",
        "_fonte": "oferta_conversao_snapshot",
    }


def ciclo_chat():
    perguntas = buscar_perguntas()
    ok = 0
    ctx_f = carregar_contexto_fechamento_ml()
    sinal_ads = ctx_f.get("sinal_ads")
    oferta = ctx_f.get("oferta")
    link_oferta = str(ctx_f.get("link_ml") or "")

    for p in perguntas:
        texto = p.get("text", "").strip()

        if not pergunta_valida(texto):
            continue

        produto = _montar_produto_resposta(p, ctx_f)

        try:
            # Perguntas de manicure: CTA alinhado à conversão + pressão Ads
            from integracoes.social.conversao_manicures import (
                pergunta_parece_manicure,
                resposta_chat_ml_haiku,
            )

            if pergunta_parece_manicure(texto) and (link_oferta or produto):
                link = link_oferta or "https://www.mercadolivre.com.br"
                resposta = resposta_chat_ml_haiku(
                    texto,
                    link,
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
            # Só aplica gate de estoque se produto veio do Bling (não do snapshot)
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

    out = {
        "chat": ciclo_chat(),
        "reputacao": verificar_reputacao(),
        "contexto_fechamento": {
            "ok": carregar_contexto_fechamento_ml().get("ok"),
            "link_valido": carregar_contexto_fechamento_ml().get("link_valido"),
            "sustentabilidade": carregar_contexto_fechamento_ml().get("sustentabilidade"),
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
