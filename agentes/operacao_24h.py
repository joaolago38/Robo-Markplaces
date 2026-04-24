"""
agentes/operacao_24h.py
Rotina contínua de monitoramento + faturamento (Lojahub -> Bling).
"""
from __future__ import annotations

import logging

from agentes.algoritmo_marketplaces import executar as executar_algoritmo_marketplaces
from agentes.ml.agente_ads_gatilho import executar as verificar_gatilho_ads
from agentes.repricing.agente_repricing_marketplaces import executar as executar_repricing_marketplaces
from agentes.repricing.agente_repricing_impala import executar as repricing_impala
from agentes.faturamento.agente_faturamento import emitir_nfe_pedido
from core.alertas_esmaltes import verificar_todos as verificar_alertas_esmaltes
from core.notificador import alertar_gestor
from integracoes.bling.bling_client import listar_produtos
from integracoes.lojahub.lojahub_client import listar_pedidos_prontos_faturar, listar_resumo_vendas_24h

logger = logging.getLogger("operacao_24h")


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _index_custo_por_sku(produtos: list[dict]) -> dict:
    return {str(p.get("sku", "")).strip(): _to_float(p.get("custo", 0.0)) for p in produtos if p.get("sku")}


def _normalizar_pedido_lojahub(pedido: dict) -> dict:
    cliente = pedido.get("cliente", {})
    itens = pedido.get("itens", pedido.get("items", []))
    return {
        "pedido_id": str(pedido.get("id", pedido.get("pedido_id", ""))),
        "cliente": {
            "nome": cliente.get("nome", cliente.get("name", "Consumidor Final")),
            "documento": cliente.get("documento", cliente.get("document", "")),
            "email": cliente.get("email", ""),
            "telefone": cliente.get("telefone", ""),
            "endereco": cliente.get("endereco", {}),
        },
        "itens": [
            {
                "sku": i.get("sku", i.get("codigo")),
                "quantidade": i.get("quantidade", i.get("quantity", 1)),
                "valor_unitario": i.get("valor_unitario", i.get("price", 0)),
                "descricao": i.get("descricao", i.get("name", "")),
                "ncm": i.get("ncm"),
            }
            for i in itens
        ],
        "observacoes": pedido.get("observacoes", pedido.get("notes", "")),
    }


def _calcular_kpis_24h(produtos_bling: list[dict], pedidos_faturar: list[dict], analytics_24h: dict) -> dict:
    preco_medio = 0.0
    if produtos_bling:
        preco_medio = sum(_to_float(p.get("preco", 0.0)) for p in produtos_bling) / len(produtos_bling)

    custo_por_sku = _index_custo_por_sku(produtos_bling)
    receita = 0.0
    custo = 0.0
    itens_vendidos = 0

    for pedido in pedidos_faturar:
        for item in pedido.get("itens", pedido.get("items", [])):
            sku = str(item.get("sku", item.get("codigo", ""))).strip()
            qtd = _to_float(item.get("quantidade", item.get("quantity", 1)), 1)
            valor = _to_float(item.get("valor_unitario", item.get("price", 0.0)), 0.0)
            receita += valor * qtd
            custo += _to_float(custo_por_sku.get(sku, 0.0)) * qtd
            itens_vendidos += int(qtd)

    ticket_medio = (receita / max(1, len(pedidos_faturar))) if pedidos_faturar else 0.0
    lucro = receita - custo
    margem_pct = (lucro / receita * 100) if receita > 0 else 0.0

    # Se analytics da API existir, usa como referência complementar.
    analytics_data = analytics_24h.get("data", {}) if analytics_24h.get("ok") else {}
    receita_ref = _to_float(analytics_data.get("receita", receita))
    pedidos_ref = int(_to_float(analytics_data.get("pedidos", len(pedidos_faturar))))

    return {
        "preco_medio_cadastrado": round(preco_medio, 2),
        "media_venda_24h": round(receita_ref / max(1, pedidos_ref), 2),
        "receita_24h": round(receita_ref, 2),
        "lucro_estimado_24h": round(lucro, 2),
        "margem_estimada_24h_pct": round(margem_pct, 2),
        "pedidos_24h": pedidos_ref,
        "itens_vendidos_24h": itens_vendidos,
        "ticket_medio_24h": round(ticket_medio, 2),
    }


def _faturar_pedidos_lojahub(dry_run_nfe: bool = False, limite: int = 20) -> dict:
    pedidos_raw = listar_pedidos_prontos_faturar(limit=limite)
    pedidos = [_normalizar_pedido_lojahub(p) for p in pedidos_raw]
    resultados = []
    sucesso = 0
    for pedido in pedidos:
        if not pedido.get("pedido_id"):
            continue
        out = emitir_nfe_pedido(pedido, dry_run=dry_run_nfe)
        if out.get("ok"):
            sucesso += 1
        resultados.append({"pedido_id": pedido["pedido_id"], "ok": out.get("ok"), "resultado": out})
    return {"total": len(resultados), "sucesso": sucesso, "falhas": len(resultados) - sucesso, "itens": resultados}


def executar(dry_run_repricing: bool = True, dry_run_nfe: bool = False) -> dict:
    produtos = listar_produtos()
    analytics = listar_resumo_vendas_24h()
    pedidos_faturar = listar_pedidos_prontos_faturar(limit=100)
    kpis = _calcular_kpis_24h(produtos, pedidos_faturar, analytics)

    # Busca reputação real da conta ML para usar nos alertas e gatilho de ads
    try:
        from integracoes.ml.ml_client import buscar_reputacao_vendedor
        _rep = buscar_reputacao_vendedor()
        _metrics = _rep.get("metrics", {})
        _total_avaliacoes = int(_metrics.get("total_ratings", 0) or 0)
        _nota_media = float(_metrics.get("average_rating", 0.0) or 0.0)
        _acos_atual = float(_metrics.get("acos", 0.0) or 0.0)
        _full_ativo = bool(_metrics.get("power_seller_status") in ("gold", "platinum"))
    except Exception as _e:
        logger.warning("Não foi possível buscar reputação ML: %s", _e)
        _total_avaliacoes = 0
        _nota_media = 0.0
        _acos_atual = 0.0
        _full_ativo = False

    # Alertas específicos de esmaltes com dados reais
    alertas_esmaltes = verificar_alertas_esmaltes(
        total_avaliacoes=_total_avaliacoes,
        kits=produtos,
    )

    # Verificar se é hora de ligar/escalar/pausar ads com dados reais
    gatilho_ads = verificar_gatilho_ads(acos_atual=_acos_atual, full_ativo=_full_ativo)

    # Repricing consciente de fase
    repricing_fases = repricing_impala(dry_run=dry_run_repricing)

    monitor_marketplaces = executar_algoritmo_marketplaces(alertar_quando_atencao=False)
    repricing = executar_repricing_marketplaces(produtos=produtos, dry_run=dry_run_repricing)
    faturamento = _faturar_pedidos_lojahub(dry_run_nfe=dry_run_nfe, limite=30)

    payload = {
        "kpis_24h": kpis,
        "marketplaces": monitor_marketplaces,
        "repricing": repricing,
        "repricing_fases": repricing_fases,
        "faturamento": faturamento,
        "alertas_esmaltes": alertas_esmaltes,
        "gatilho_ads": gatilho_ads,
        "modo": {"repricing_dry_run": dry_run_repricing, "nfe_dry_run": dry_run_nfe},
    }

    alertar_gestor(
        f"Operação 24h:\n"
        f"Receita: R$ {kpis['receita_24h']:.2f} | Lucro estimado: R$ {kpis['lucro_estimado_24h']:.2f}\n"
        f"Preço médio: R$ {kpis['preco_medio_cadastrado']:.2f} | Ticket médio: R$ {kpis['ticket_medio_24h']:.2f}\n"
        f"NF geradas: {faturamento['sucesso']}/{faturamento['total']} | Ajustes preço: {repricing['total_ajustes']}"
    )
    logger.info("Operacao24h: %s", payload)
    return payload


if __name__ == "__main__":
    print(executar(dry_run_repricing=True, dry_run_nfe=False))
