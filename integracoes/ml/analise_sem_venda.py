"""
integracoes/ml/analise_sem_venda.py
Detecta anúncios próprios sem venda no período e sugere ação (preço/ads/listing).
"""
from __future__ import annotations

from typing import Any


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _i(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def sugerir_acao(
    *,
    visitas_30d: int,
    visitas_altas: int = 20,
) -> str:
    if visitas_30d >= visitas_altas:
        return "baixar_preco_ou_listing"
    if visitas_30d > 0:
        return "melhorar_titulo_e_ads"
    return "republicar_ou_ads"


def _rotulo_acao(acao: str) -> str:
    return {
        "baixar_preco_ou_listing": "Visitas sem conversão → baixar preço / frete / fotos",
        "melhorar_titulo_e_ads": "Poucas visitas → título + Product Ads leve",
        "republicar_ou_ads": "Sem visitas → ads ou republicar anúncio",
    }.get(acao, acao)


def analisar_anuncios_sem_venda(
    anuncios: list[dict[str, Any]],
    item_ids_com_venda: set[str],
    metricas_por_item: dict[str, dict[str, Any]] | None = None,
    *,
    dias: int = 30,
    visitas_altas: int = 20,
    max_itens: int = 40,
) -> dict[str, Any]:
    """
    anuncios: listar_meus_anuncios()
    item_ids_com_venda: IDs que apareceram em pedidos dos últimos `dias`
    metricas_por_item: item_id -> buscar_metricas_item()
    """
    metricas_por_item = metricas_por_item or {}
    vendidos = {str(x).strip() for x in item_ids_com_venda if str(x).strip()}
    sem_venda: list[dict[str, Any]] = []

    for anuncio in anuncios or []:
        if not isinstance(anuncio, dict):
            continue
        item_id = str(anuncio.get("item_id") or "").strip()
        if not item_id or item_id in vendidos:
            continue
        if "PREENCHER" in item_id.upper():
            continue
        m = metricas_por_item.get(item_id) or {}
        visitas_30d = _i(m.get("visitas_30d"), 0)
        visitas_7d = _i(m.get("visitas_7d"), 0)
        acao = sugerir_acao(visitas_30d=visitas_30d, visitas_altas=visitas_altas)
        sem_venda.append(
            {
                "item_id": item_id,
                "sku": str(anuncio.get("sku") or m.get("sku") or ""),
                "titulo": str(anuncio.get("titulo") or m.get("titulo") or "")[:80],
                "preco": _f(anuncio.get("preco") or m.get("preco")),
                "sold_quantity_total": _i(anuncio.get("sold_quantity") or m.get("sold_quantity")),
                "visitas_7d": visitas_7d,
                "visitas_30d": visitas_30d,
                "acao": acao,
                "acao_rotulo": _rotulo_acao(acao),
            }
        )

    sem_venda.sort(key=lambda x: (-int(x.get("visitas_30d") or 0), str(x.get("titulo") or "")))
    if max_itens > 0:
        sem_venda = sem_venda[:max_itens]

    por_acao: dict[str, int] = {}
    for row in sem_venda:
        por_acao[row["acao"]] = por_acao.get(row["acao"], 0) + 1

    return {
        "ok": True,
        "dias": dias,
        "total_anuncios": len(anuncios or []),
        "total_com_venda": len(vendidos),
        "total_sem_venda": len(sem_venda),
        "por_acao": por_acao,
        "itens": sem_venda,
    }


def montar_mensagem_sem_venda(analise: dict[str, Any]) -> str:
    dias = int(analise.get("dias") or 30)
    itens = analise.get("itens") or []
    linhas = [
        f"📉 *Anúncios ML sem venda — {dias}d*",
        f"• Ativos: {analise.get('total_anuncios', 0)} | "
        f"com venda: {analise.get('total_com_venda', 0)} | "
        f"*sem venda: {analise.get('total_sem_venda', 0)}*",
    ]
    por_acao = analise.get("por_acao") or {}
    if por_acao:
        linhas.append(
            "• Ações: "
            + ", ".join(f"{k.replace('_', ' ')}={v}" for k, v in sorted(por_acao.items()))
        )
    if not itens:
        linhas.append("")
        linhas.append("_Nenhum anúncio ativo sem venda no período._")
        return "\n".join(linhas)

    linhas.append("")
    linhas.append("*Prioridade (mais visitas primeiro)*")
    for row in itens[:12]:
        sku = row.get("sku") or row.get("item_id")
        linhas.append(
            f"• `{sku}` R$ {_f(row.get('preco')):.2f} | "
            f"visitas 30d={_i(row.get('visitas_30d'))} | "
            f"{row.get('acao_rotulo')}"
        )
        tit = str(row.get("titulo") or "").strip()
        if tit:
            linhas.append(f"  _{tit}_")
    if len(itens) > 12:
        linhas.append(f"• … +{len(itens) - 12} outros")
    return "\n".join(linhas)
