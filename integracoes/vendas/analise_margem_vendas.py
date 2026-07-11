"""
integracoes/vendas/analise_margem_vendas.py
Calcula margem operacional das vendas dos marketplaces (preço − taxa − custo).
"""
from __future__ import annotations

from typing import Any

from core.config import MARGEM_MINIMA, TAXA_CANAL_PADRAO_PCT
from core.precificacao_comportamento import calcular_lucro_operacao

_CANAL_POR_MP = {
    "mercadolivre": "mercadolivre",
    "shopee": "shopee",
    "magalu": "magalu",
    "amazon": "amazon",
}

_NOME_MP = {
    "mercadolivre": "Mercado Livre",
    "shopee": "Shopee",
    "magalu": "Magalu",
    "amazon": "Amazon",
}


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def indexar_produtos_por_sku(produtos: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in produtos or []:
        if not isinstance(p, dict):
            continue
        sku = str(p.get("sku") or "").strip()
        if sku:
            out[sku] = p
    return out


def taxa_canal_produto(produto: dict[str, Any] | None, marketplace: str) -> float:
    if not produto:
        return TAXA_CANAL_PADRAO_PCT
    canal = _CANAL_POR_MP.get((marketplace or "").strip().lower(), "")
    dados = (produto.get("canais") or {}).get(canal) or {}
    taxa = _f(dados.get("taxa_canal_pct"), 0.0)
    return taxa if taxa > 0 else TAXA_CANAL_PADRAO_PCT


def custo_produto(produto: dict[str, Any] | None) -> float:
    if not produto:
        return 0.0
    for chave in ("custo", "custo_total"):
        v = _f(produto.get(chave))
        if v > 0:
            return v
    return 0.0


def analisar_item_venda(
    *,
    marketplace: str,
    order_id: str,
    item: dict[str, Any],
    produtos_por_sku: dict[str, dict[str, Any]],
    margem_min_pct: float | None = None,
) -> dict[str, Any]:
    """Analisa um item de pedido. Nunca lança."""
    min_pct = margem_min_pct if margem_min_pct is not None else MARGEM_MINIMA
    sku = str(item.get("sku") or "").strip()
    qtd = max(1, int(item.get("quantidade") or 1))
    preco_unit = _f(item.get("preco_unitario"))
    if preco_unit <= 0 and qtd > 0:
        # fallback raro: alguns clients só trazem total no pedido
        preco_unit = _f(item.get("preco") or item.get("total")) / qtd

    produto = produtos_por_sku.get(sku) if sku else None
    custo = custo_produto(produto)
    taxa = taxa_canal_produto(produto, marketplace)
    receita_bruta = round(preco_unit * qtd, 2)

    status = "ok"
    lucro = calcular_lucro_operacao(preco_unit, custo, taxa) if preco_unit > 0 and custo > 0 else {
        "receita_liquida": round(preco_unit * (1 - taxa / 100.0), 2) if preco_unit > 0 else 0.0,
        "lucro_reais": 0.0,
        "margem_operacional_pct": 0.0,
    }

    if not sku:
        status = "sem_sku"
    elif custo <= 0:
        status = "sem_custo"
    elif preco_unit <= 0:
        status = "sem_preco"
    else:
        margem = float(lucro.get("margem_operacional_pct") or 0)
        if float(lucro.get("lucro_reais") or 0) < 0:
            status = "prejuizo"
        elif margem < min_pct:
            status = "margem_baixa"

    lucro_total = round(float(lucro.get("lucro_reais") or 0) * qtd, 2)
    liquida_total = round(float(lucro.get("receita_liquida") or 0) * qtd, 2)

    return {
        "chave": f"{marketplace}:{order_id}:{sku or item.get('item_id') or 'item'}",
        "marketplace": marketplace,
        "order_id": str(order_id),
        "sku": sku,
        "item_id": str(item.get("item_id") or ""),
        "quantidade": qtd,
        "preco_unitario": round(preco_unit, 2),
        "receita_bruta": receita_bruta,
        "receita_liquida": liquida_total,
        "custo_unitario": round(custo, 2),
        "custo_total": round(custo * qtd, 2),
        "taxa_canal_pct": round(taxa, 2),
        "lucro_reais": lucro_total,
        "margem_operacional_pct": float(lucro.get("margem_operacional_pct") or 0),
        "status": status,
        "abaixo_minimo": status in {"prejuizo", "margem_baixa"},
    }


def analisar_pedidos(
    pedidos_por_marketplace: dict[str, list[dict[str, Any]]],
    produtos: list[dict[str, Any]] | None,
    *,
    margem_min_pct: float | None = None,
) -> dict[str, Any]:
    """
    Agrega margem de todos os itens dos pedidos.
    pedidos_por_marketplace: { "mercadolivre": [pedido, ...], ... }
    """
    min_pct = margem_min_pct if margem_min_pct is not None else MARGEM_MINIMA
    index = indexar_produtos_por_sku(produtos)
    linhas: list[dict[str, Any]] = []

    for mp, pedidos in (pedidos_por_marketplace or {}).items():
        for pedido in pedidos or []:
            if not isinstance(pedido, dict):
                continue
            order_id = str(pedido.get("order_id") or "").strip()
            if not order_id:
                continue
            itens = pedido.get("itens") or []
            if not itens:
                # pedido sem itens detalhados — analisa como 1 linha pelo total
                itens = [{
                    "sku": str(pedido.get("produto") or pedido.get("sku") or ""),
                    "quantidade": int(pedido.get("quantidade") or 1),
                    "preco_unitario": _f(pedido.get("total")),
                }]
            for item in itens:
                if not isinstance(item, dict):
                    continue
                linhas.append(
                    analisar_item_venda(
                        marketplace=str(mp),
                        order_id=order_id,
                        item=item,
                        produtos_por_sku=index,
                        margem_min_pct=min_pct,
                    )
                )

    com_margem = [l for l in linhas if l["status"] not in {"sem_custo", "sem_sku", "sem_preco"}]
    alertas = [l for l in linhas if l.get("abaixo_minimo")]
    incompletos = [l for l in linhas if l["status"] in {"sem_custo", "sem_sku", "sem_preco"}]

    receita_bruta = round(sum(l["receita_bruta"] for l in linhas), 2)
    lucro_total = round(sum(l["lucro_reais"] for l in com_margem), 2)
    if com_margem and receita_bruta > 0:
        # margem média ponderada pela receita das linhas com custo
        rec_com = sum(l["receita_bruta"] for l in com_margem) or 1.0
        margem_media = round(
            sum(l["margem_operacional_pct"] * l["receita_bruta"] for l in com_margem) / rec_com,
            2,
        )
    else:
        margem_media = 0.0

    por_mp: dict[str, dict[str, Any]] = {}
    for l in linhas:
        mp = l["marketplace"]
        bucket = por_mp.setdefault(
            mp,
            {"vendas": 0, "receita_bruta": 0.0, "lucro_reais": 0.0, "alertas": 0, "incompletos": 0},
        )
        bucket["vendas"] += 1
        bucket["receita_bruta"] = round(bucket["receita_bruta"] + l["receita_bruta"], 2)
        if l["status"] not in {"sem_custo", "sem_sku", "sem_preco"}:
            bucket["lucro_reais"] = round(bucket["lucro_reais"] + l["lucro_reais"], 2)
        if l.get("abaixo_minimo"):
            bucket["alertas"] += 1
        if l["status"] in {"sem_custo", "sem_sku", "sem_preco"}:
            bucket["incompletos"] += 1

    return {
        "ok": True,
        "margem_min_pct": min_pct,
        "total_itens": len(linhas),
        "total_com_margem": len(com_margem),
        "total_alertas": len(alertas),
        "total_incompletos": len(incompletos),
        "receita_bruta": receita_bruta,
        "lucro_reais": lucro_total,
        "margem_media_pct": margem_media,
        "linhas": linhas,
        "alertas": alertas,
        "incompletos": incompletos,
        "por_marketplace": por_mp,
    }


def _fmt_brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def montar_mensagem_alerta_baixa(
    linha: dict[str, Any],
    *,
    margem_min_pct: float,
) -> str:
    mp = _NOME_MP.get(linha.get("marketplace") or "", linha.get("marketplace") or "?")
    status = linha.get("status") or "margem_baixa"
    titulo = "Prejuízo na venda" if status == "prejuizo" else "Margem abaixo do mínimo"
    return (
        f"📉 *{titulo}*\n"
        f"• Canal: {mp}\n"
        f"• Pedido: `{linha.get('order_id')}`\n"
        f"• SKU: `{linha.get('sku') or '—'}` × {linha.get('quantidade')}\n"
        f"• Preço unit.: {_fmt_brl(float(linha.get('preco_unitario') or 0))}\n"
        f"• Custo unit.: {_fmt_brl(float(linha.get('custo_unitario') or 0))}\n"
        f"• Taxa canal: {float(linha.get('taxa_canal_pct') or 0):.1f}%\n"
        f"• Lucro: {_fmt_brl(float(linha.get('lucro_reais') or 0))}\n"
        f"• Margem: *{float(linha.get('margem_operacional_pct') or 0):.1f}%* "
        f"(mín. {margem_min_pct:.1f}%)"
    )


def montar_mensagem_resumo(analise: dict[str, Any], *, dias: int) -> str:
    linhas = [
        f"💰 *Margem das vendas — últimos {dias}d*",
        f"• Itens: {analise.get('total_itens', 0)} "
        f"({analise.get('total_com_margem', 0)} com custo)",
        f"• Receita bruta: {_fmt_brl(float(analise.get('receita_bruta') or 0))}",
        f"• Lucro est.: {_fmt_brl(float(analise.get('lucro_reais') or 0))}",
        f"• Margem média: *{float(analise.get('margem_media_pct') or 0):.1f}%* "
        f"(mín. {float(analise.get('margem_min_pct') or 0):.1f}%)",
        f"• Abaixo do mínimo: {analise.get('total_alertas', 0)}",
        f"• Sem custo/SKU: {analise.get('total_incompletos', 0)}",
    ]
    por_mp = analise.get("por_marketplace") or {}
    if por_mp:
        linhas.append("")
        linhas.append("*Por canal*")
        for mp, bucket in sorted(por_mp.items()):
            nome = _NOME_MP.get(mp, mp)
            linhas.append(
                f"• {nome}: {bucket.get('vendas', 0)} it. | "
                f"{_fmt_brl(float(bucket.get('receita_bruta') or 0))} | "
                f"lucro {_fmt_brl(float(bucket.get('lucro_reais') or 0))}"
            )

    alertas = analise.get("alertas") or []
    if alertas:
        linhas.append("")
        linhas.append("*Piores margens*")
        ordenados = sorted(alertas, key=lambda x: float(x.get("margem_operacional_pct") or 0))
        for a in ordenados[:5]:
            nome = _NOME_MP.get(a.get("marketplace") or "", a.get("marketplace"))
            linhas.append(
                f"• {nome} `{a.get('sku') or a.get('order_id')}`: "
                f"{float(a.get('margem_operacional_pct') or 0):.1f}% "
                f"({_fmt_brl(float(a.get('lucro_reais') or 0))})"
            )
    return "\n".join(linhas)
