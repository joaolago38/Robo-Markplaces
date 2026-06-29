"""
agentes/vendas_notificador.py
Verifica novas vendas em todos os marketplaces e envia notificação WhatsApp.
Mantém controle de pedidos já notificados para não duplicar mensagens.
Nunca lança exceção.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from core.config import ROOT
from core.notificador import alertar_critico
from core.whatsapp import notificar_venda

logger = logging.getLogger("vendas_notificador")

PEDIDOS_NOTIFICADOS_PATH: Path = ROOT / "dados" / "pedidos_notificados.json"


def _carregar_notificados() -> set[str]:
    """Carrega IDs de pedidos já notificados do arquivo de controle."""
    try:
        PEDIDOS_NOTIFICADOS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if PEDIDOS_NOTIFICADOS_PATH.exists():
            data = json.loads(PEDIDOS_NOTIFICADOS_PATH.read_text(encoding="utf-8"))
            return set(data.get("notificados", []))
    except Exception as exc:
        logger.error("Erro ao carregar pedidos notificados: %s", exc)
    return set()


def _salvar_notificados(ids: set[str]) -> None:
    """Salva IDs de pedidos já notificados no arquivo de controle."""
    try:
        PEDIDOS_NOTIFICADOS_PATH.parent.mkdir(parents=True, exist_ok=True)
        lista = sorted(ids)[-1000:]
        PEDIDOS_NOTIFICADOS_PATH.write_text(
            json.dumps({"notificados": lista}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.error("Erro ao salvar pedidos notificados: %s", exc)


def _checar_busca_falhou(marketplace: str, ok: bool) -> None:
    """
    Quando a chamada à API falhou de verdade (token expirado, API fora do
    ar, etc.), `pedidos` volta vazio igual a "sem venda nova" — sem isto,
    as duas situações são indistinguíveis e o time nunca saberia que está
    cego para vendas reais enquanto o problema persistir.
    """
    if not ok:
        logger.error(
            "%s: busca de pedidos FALHOU (não é 'sem vendas novas' — a chamada não completou).",
            marketplace,
        )
        alertar_critico(
            f"⚠️ Não consegui buscar pedidos novos no {marketplace}.\n"
            "Isso pode significar que vendas reais não estão sendo notificadas. "
            "Verifique o token/credenciais e o status da API."
        )


def _notificar_novos_pedidos(
    marketplace: str, pedidos: list[dict], notificados: set[str]
) -> set[str]:
    """
    Para cada pedido da lista, envia WhatsApp se ainda não foi notificado.
    Retorna conjunto com as chaves recém-notificadas (marketplace:order_id).
    """
    novos: set[str] = set()
    for pedido in pedidos:
        pedido_id = str(pedido.get("order_id", ""))
        chave = f"{marketplace}:{pedido_id}"

        if not pedido_id or chave in notificados:
            continue

        itens = pedido.get("itens", [])
        if itens:
            produto = (
                itens[0].get("sku", "Produto") if len(itens) == 1 else f"{len(itens)} itens"
            )
            quantidade = sum(int(i.get("quantidade", 1) or 1) for i in itens)
        else:
            produto = str(pedido.get("produto", "Produto"))
            quantidade = int(pedido.get("quantidade", 1) or 1)

        try:
            valor = float(pedido.get("total", 0) or 0)
        except (TypeError, ValueError):
            valor = 0.0

        ok = notificar_venda(
            marketplace=marketplace,
            pedido_id=pedido_id,
            produto=produto,
            valor=valor,
            quantidade=quantidade,
        )

        if ok:
            novos.add(chave)
            logger.info(
                "WhatsApp notificado: %s pedido %s valor R$ %.2f",
                marketplace,
                pedido_id,
                valor,
            )
        else:
            logger.warning("WhatsApp FALHOU: %s pedido %s", marketplace, pedido_id)

    return novos


def notificar_pedidos_novos_marketplace(marketplace: str) -> dict:
    """
    Processa apenas um marketplace (ex.: ao final de cada agente de chat).
    Retorna resumo com quantidade de notificações enviadas.
    """
    mp = (marketplace or "").strip().lower()
    novos: set[str] = set()
    res: dict = {"marketplace": mp, "notificacoes": 0}
    try:
        notificados = _carregar_notificados()
        pedidos: list[dict] = []
        if mp == "mercadolivre":
            from integracoes.ml.ml_client import listar_pedidos_detalhado as lp_detalhado

            pedidos, ok = lp_detalhado(dias=1)
            _checar_busca_falhou("Mercado Livre", ok)
        elif mp == "shopee":
            from integracoes.shopee.shopee_client import listar_pedidos as lp

            pedidos = lp(dias=1)
        elif mp == "magalu":
            from integracoes.magalu.magalu_client import listar_pedidos_detalhado as lp_detalhado

            pedidos, ok = lp_detalhado(dias=1)
            _checar_busca_falhou("Magalu", ok)
        elif mp == "amazon":
            from integracoes.amazon.amazon_client import listar_pedidos as lp

            pedidos = lp(dias=1)
        else:
            logger.warning("Marketplace desconhecido para vendas WhatsApp: %s", marketplace)
            return res

        novos = _notificar_novos_pedidos(mp, pedidos, notificados)
        if novos:
            _salvar_notificados(notificados | novos)
    except Exception as exc:
        logger.error("notificar_pedidos_novos_marketplace %s: %s", mp, exc)
    res["notificacoes"] = len(novos)
    return res


def executar() -> dict:
    """
    Verifica novas vendas em todos os marketplaces e notifica via WhatsApp.
    Retorna resumo com total de notificações enviadas por marketplace.
    """
    notificados = _carregar_notificados()
    novos_total: set[str] = set()
    resumo: dict[str, int] = {}

    try:
        from integracoes.ml.ml_client import listar_pedidos_detalhado

        pedidos_ml, ok_ml = listar_pedidos_detalhado(dias=1)
        _checar_busca_falhou("Mercado Livre", ok_ml)
        novos_ml = _notificar_novos_pedidos("mercadolivre", pedidos_ml, notificados)
        resumo["mercadolivre"] = len(novos_ml)
        novos_total.update(novos_ml)
        notificados |= novos_ml
    except Exception as exc:
        logger.error("Erro ao buscar pedidos ML: %s", exc)
        resumo["mercadolivre"] = 0

    try:
        from integracoes.shopee.shopee_client import listar_pedidos as shopee_pedidos

        pedidos_shopee = shopee_pedidos(dias=1)
        novos_shopee = _notificar_novos_pedidos("shopee", pedidos_shopee, notificados)
        resumo["shopee"] = len(novos_shopee)
        novos_total.update(novos_shopee)
        notificados |= novos_shopee
    except Exception as exc:
        logger.error("Erro ao buscar pedidos Shopee: %s", exc)
        resumo["shopee"] = 0

    try:
        from integracoes.magalu.magalu_client import listar_pedidos_detalhado as magalu_pedidos_detalhado

        pedidos_magalu, ok_magalu = magalu_pedidos_detalhado(dias=1)
        _checar_busca_falhou("Magalu", ok_magalu)
        novos_magalu = _notificar_novos_pedidos("magalu", pedidos_magalu, notificados)
        resumo["magalu"] = len(novos_magalu)
        novos_total.update(novos_magalu)
        notificados |= novos_magalu
    except Exception as exc:
        logger.error("Erro ao buscar pedidos Magalu: %s", exc)
        resumo["magalu"] = 0

    try:
        from integracoes.amazon.amazon_client import listar_pedidos as amazon_pedidos

        pedidos_amazon = amazon_pedidos(dias=1)
        novos_amazon = _notificar_novos_pedidos("amazon", pedidos_amazon, notificados)
        resumo["amazon"] = len(novos_amazon)
        novos_total.update(novos_amazon)
        notificados |= novos_amazon
    except Exception as exc:
        logger.error("Erro ao buscar pedidos Amazon: %s", exc)
        resumo["amazon"] = 0

    if novos_total:
        _salvar_notificados(notificados)

    total = sum(resumo.values())
    logger.info("Notificações WhatsApp enviadas: %d | Detalhe: %s", total, resumo)
    return {"total_notificacoes": total, "por_marketplace": resumo}


if __name__ == "__main__":
    import pprint

    pprint.pprint(executar())
