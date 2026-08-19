"""
agentes/ml/agente_ml.py
Chat ML + reputação. Dono único das respostas ML no ciclo 30min.
Usa snapshot conversão (Ads/oferta) e mapeia MLB→SKU via catálogo.
"""

import logging
import time

from core.atomic_io import escrever_json_atomico
from core.chat_claim import tentar_claim
from core.chat_seguro_ml import (
    MSG_CONFIRMAR,
    MSG_ESTOQUE_INCERTO,
    MSG_INDISPONIVEL,
    sanitizar_resposta_chat_ml,
)
from core.claude_client import responder_chat
from core.config import MARGEM_MINIMA, ROOT, skip_se_spec_inativo
from core.contexto_fechamento_ml import carregar_contexto_fechamento_ml
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_critico, alertar_gestor
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
_TAG_ML = ["marketplace:mercadolivre"]
HEARTBEAT_PATH = ROOT / "logs" / "chat_ultima.json"
_ultimo_ciclo_chat: dict[str, int] = {"respondidas": 0, "falhas": 0, "fila": 0}


def pergunta_valida(texto: str) -> bool:
    return bool(texto and len(texto.strip()) >= 3)


def validar_resposta(resposta: str, produto: dict) -> str:
    """
    Porta única antes de publicar no ML:
    estoque Bling (fail-closed), sem inventar frete/prazo/preço/desconto.
    """
    if not produto:
        return MSG_CONFIRMAR

    fonte = str(produto.get("_fonte") or "")
    # Snapshot de conversão: estoque desconhecido — não afirmar disponibilidade
    if fonte == "oferta_conversao_snapshot":
        return sanitizar_resposta_chat_ml(resposta, produto)

    sku = str(produto.get("sku") or produto.get("codigo") or "").strip()
    if sku:
        try:
            produto_bling = buscar_produto(sku)
        except Exception as exc:
            logger.warning("validar_resposta: Bling falhou sku=%s: %s", sku, exc)
            return MSG_ESTOQUE_INCERTO
        if not produto_bling:
            return MSG_ESTOQUE_INCERTO
        estoque = int(produto_bling.get("estoque", 0) or 0)
        produto = {**produto, "estoque": estoque, "preco": produto_bling.get("preco") or produto.get("preco")}
    else:
        estoque = int(produto.get("estoque", 0) or 0)

    if estoque <= 0:
        return MSG_INDISPONIVEL

    return sanitizar_resposta_chat_ml(resposta, produto)


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
    from core.algoritmo_eventos import deve_priorizar_chat

    priorizar, motivo_prio = deve_priorizar_chat("mercadolivre")
    if priorizar:
        logger.warning("Chat ML em modo prioridade (algoritmo): %s", motivo_prio)
        alertar_gestor(
            f"⚡ *Chat ML priorizado*\n_{motivo_prio}_\nEsvaziando fila de perguntas.",
            chave="chat_ml:priorizar",
            cooldown_segundos=1800,
            agente_id="chat_ml",
        )

    perguntas = buscar_perguntas()
    ok = 0
    falhas = 0
    ctx_f = carregar_contexto_fechamento_ml()
    sinal_ads = ctx_f.get("sinal_ads")
    oferta = ctx_f.get("oferta")
    link_oferta = str(ctx_f.get("link_ml") or "")
    link_ok = bool(ctx_f.get("link_valido"))

    gauge("chat.fila", float(len(perguntas or [])), tags=_TAG_ML)

    # Em prioridade, processa a fila completa sem cortar cedo
    for p in perguntas:
        texto = p.get("text", "").strip()
        pid = str(p.get("id") or "")

        if not pergunta_valida(texto):
            continue

        if not tentar_claim("mercadolivre", pid, agente="chat_ml", fail_closed=True):
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
                    produto=produto if isinstance(produto, dict) else None,
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
            # Sempre: Bling + anti-invenção antes de publicar
            resposta = validar_resposta(resposta, produto)

        except Exception as e:
            logger.error(f"Erro IA: {e}")
            resposta = MSG_CONFIRMAR

        if responder(p["id"], resposta):
            ok += 1
        else:
            falhas += 1

        logger.info(
            "%s -> %s | contexto_ads=%s oferta=%s",
            texto,
            resposta,
            bool(sinal_ads),
            (oferta or {}).get("campanha_id"),
        )

        time.sleep(1)

    if ok:
        incrementar("chat.respondidas", float(ok), tags=_TAG_ML)
    if falhas:
        incrementar("chat.falha", float(falhas), tags=_TAG_ML)
    incrementar("chat.rodadas", tags=_TAG_ML)
    global _ultimo_ciclo_chat
    _ultimo_ciclo_chat = {
        "respondidas": int(ok),
        "falhas": int(falhas),
        "fila": len(perguntas or []),
    }
    try:
        from datetime import datetime, timezone

        escrever_json_atomico(
            HEARTBEAT_PATH,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": falhas == 0,
                "marketplace": "mercadolivre",
                "respondidas": ok,
                "falhas": falhas,
                "fila": len(perguntas or []),
            },
        )
    except Exception as exc:
        logger.warning("Chat ML heartbeat: %s", exc)
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
    pulado = skip_se_spec_inativo("mercadolivre")
    if pulado:
        logger.info("Chat ML pulado — spec.inativo")
        return pulado
    logger.info("Agente ML iniciado")

    ctx = carregar_contexto_fechamento_ml()
    chat_ok = ciclo_chat()
    reputacao = verificar_reputacao()
    p0: dict = {}
    try:
        from integracoes.ml.alerta_pendencias_loja import emitir_alerta_p0_do_ciclo

        p0 = emitir_alerta_p0_do_ciclo(
            chat_falhas=int(_ultimo_ciclo_chat.get("falhas") or 0),
            perguntas_pendentes=max(
                0,
                int(_ultimo_ciclo_chat.get("fila") or 0)
                - int(_ultimo_ciclo_chat.get("respondidas") or 0),
            ),
            reputacao=reputacao if isinstance(reputacao, dict) else {},
        )
    except Exception as exc:
        logger.warning("P0 loja ML: %s", exc)
        p0 = {"tem_p0": False, "erro": str(exc)}
    out = {
        "chat": chat_ok,
        "reputacao": reputacao,
        "p0_loja": p0,
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
