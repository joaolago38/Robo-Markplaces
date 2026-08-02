"""
integracoes/filamentos/analise_masterprint_petg.py
Varredura focada: filamento PETG Masterprint no Mercado Livre.

Métricas:
  - total de anúncios ativos (únicos)
  - mais rentáveis por margem real (tabela Masterprint − taxa ML)
  - receita proxy (preço × vendas) como referência de volume
  - maior ganho (maior Δ vendas / Δ receita vs snapshot anterior)
"""
from __future__ import annotations

from typing import Any

from integracoes.filamentos.analise_filamentos_ml import (
    classificar_anuncio,
    detectar_marca,
    eh_listing_filamento,
)
from integracoes.filamentos.custos_masterprint_petg import (
    carregar_tabela_custos,
    enriquecer_com_margem,
    top_por_margem,
)

MARCA_ALVO = "Masterprint"
MATERIAL_ALVO = "PETG"


def _eh_masterprint(titulo: str, marca: str | None = None) -> bool:
    m = (marca or detectar_marca(titulo) or "").strip()
    if m == MARCA_ALVO:
        return True
    blob = f"{titulo} {m}".lower()
    return "masterprint" in blob or "master print" in blob


def classificar_masterprint_petg(anuncio: dict[str, Any]) -> dict[str, Any] | None:
    item = classificar_anuncio(anuncio, material_esperado=MATERIAL_ALVO)
    if not item:
        return None
    if not eh_listing_filamento(item.get("titulo") or "", MATERIAL_ALVO):
        return None
    if not _eh_masterprint(item.get("titulo") or "", item.get("marca")):
        return None
    preco = float(item.get("preco") or 0)
    vendidos = int(item.get("quantidade_vendida") or 0)
    item["receita_proxy"] = round(preco * max(0, vendidos), 2)
    item["marca"] = MARCA_ALVO
    item["material"] = MATERIAL_ALVO
    return item


def deduplicar(produtos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    por_id: dict[str, dict[str, Any]] = {}
    for p in produtos:
        iid = str(p.get("item_id") or "").strip()
        chave = iid or f"{p.get('titulo')}|{p.get('preco')}"
        atual = por_id.get(chave)
        if atual is None:
            por_id[chave] = dict(p)
            continue
        # Mantém o de maior vendas / receita
        if int(p.get("quantidade_vendida") or 0) > int(atual.get("quantidade_vendida") or 0):
            por_id[chave] = dict(p)
        elif float(p.get("receita_proxy") or 0) > float(atual.get("receita_proxy") or 0):
            por_id[chave] = dict(p)
    return list(por_id.values())


def top_rentaveis(produtos: list[dict[str, Any]], top_n: int = 10) -> list[dict[str, Any]]:
    """Maior receita proxy (preço × vendas)."""
    ordenados = sorted(
        produtos,
        key=lambda p: (float(p.get("receita_proxy") or 0), int(p.get("quantidade_vendida") or 0)),
        reverse=True,
    )
    out = []
    for i, p in enumerate(ordenados[:top_n], 1):
        row = dict(p)
        row["rank"] = i
        out.append(row)
    return out


def top_vendas(produtos: list[dict[str, Any]], top_n: int = 10) -> list[dict[str, Any]]:
    ordenados = sorted(
        produtos,
        key=lambda p: (int(p.get("quantidade_vendida") or 0), float(p.get("receita_proxy") or 0)),
        reverse=True,
    )
    out = []
    for i, p in enumerate(ordenados[:top_n], 1):
        row = dict(p)
        row["rank"] = i
        out.append(row)
    return out


def calcular_maiores_ganhos(
    atuais: list[dict[str, Any]],
    anteriores: list[dict[str, Any]] | None,
    *,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """
    Maior ganho = maior aumento de vendas (e receita) vs snapshot anterior.
    Sem histórico: usa top_vendas como proxy de “em alta”.
    """
    if not anteriores:
        return [
            {
                **p,
                "delta_vendas": int(p.get("quantidade_vendida") or 0),
                "delta_receita": float(p.get("receita_proxy") or 0),
                "ganho_fonte": "sem_historico_usa_vendas",
            }
            for p in top_vendas(atuais, top_n=top_n)
        ]

    prev_map: dict[str, dict[str, Any]] = {}
    for p in anteriores:
        iid = str(p.get("item_id") or "").strip()
        if iid:
            prev_map[iid] = p

    ganhos: list[dict[str, Any]] = []
    for p in atuais:
        iid = str(p.get("item_id") or "").strip()
        ant = prev_map.get(iid) or {}
        v_now = int(p.get("quantidade_vendida") or 0)
        v_old = int(ant.get("quantidade_vendida") or 0)
        r_now = float(p.get("receita_proxy") or 0)
        r_old = float(ant.get("receita_proxy") or 0)
        delta_v = v_now - v_old
        delta_r = round(r_now - r_old, 2)
        if delta_v <= 0 and delta_r <= 0:
            continue
        row = dict(p)
        row["delta_vendas"] = delta_v
        row["delta_receita"] = delta_r
        row["vendas_anterior"] = v_old
        row["ganho_fonte"] = "delta_historico"
        ganhos.append(row)

    ganhos.sort(key=lambda x: (x["delta_vendas"], x["delta_receita"]), reverse=True)
    for i, row in enumerate(ganhos[:top_n], 1):
        row["rank"] = i
    return ganhos[:top_n]


def consolidar_masterprint_petg(
    resultados_termos: list[dict[str, Any]],
    *,
    produtos_anteriores: list[dict[str, Any]] | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    todos: list[dict[str, Any]] = []
    for r in resultados_termos:
        if not r.get("ok"):
            continue
        todos.extend(r.get("produtos") or [])

    unicos = deduplicar(todos)
    tabela = carregar_tabela_custos()
    unicos = [enriquecer_com_margem(p, tabela=tabela) for p in unicos]

    precos = [float(p["preco"]) for p in unicos if float(p.get("preco") or 0) > 0]
    margens = [float(p["margem_brl"]) for p in unicos if p.get("margem_brl") is not None]
    rentaveis_margem = top_por_margem(unicos, top_n=top_n)
    rentaveis_receita = top_rentaveis(unicos, top_n=top_n)
    vendas = top_vendas(unicos, top_n=top_n)
    ganhos = calcular_maiores_ganhos(unicos, produtos_anteriores, top_n=top_n)

    return {
        "ok": True,
        "marca": MARCA_ALVO,
        "material": MATERIAL_ALVO,
        "total_anuncios_ativos": len(unicos),
        "preco_min": round(min(precos), 2) if precos else 0.0,
        "preco_max": round(max(precos), 2) if precos else 0.0,
        "preco_medio": round(sum(precos) / len(precos), 2) if precos else 0.0,
        "custo_padrao_1kg_brl": tabela.get("custo_padrao_1kg_brl"),
        "tabela_custos": tabela.get("tabela"),
        "tabela_valida_em": tabela.get("valida_a_partir_de"),
        "margem_media_brl": round(sum(margens) / len(margens), 2) if margens else None,
        "lucro_proxy_total": round(sum(float(p.get("lucro_proxy") or 0) for p in unicos), 2),
        "receita_proxy_total": round(sum(float(p.get("receita_proxy") or 0) for p in unicos), 2),
        "vendas_totais": sum(int(p.get("quantidade_vendida") or 0) for p in unicos),
        "mais_rentaveis": rentaveis_margem,
        "mais_rentaveis_receita": rentaveis_receita,
        "mais_vendidos": vendas,
        "maior_ganho": ganhos,
        "produtos": unicos,
        "termos_varridos": sum(1 for r in resultados_termos if r.get("ok")),
    }


def processar_termo_masterprint(
    segmento: dict[str, Any],
    anuncios: list[dict[str, Any]],
) -> dict[str, Any]:
    classificados: list[dict[str, Any]] = []
    for a in anuncios:
        item = classificar_masterprint_petg(a)
        if item:
            classificados.append(item)
    return {
        "ok": True,
        "id": segmento.get("id"),
        "nome": segmento.get("nome"),
        "termo_busca": segmento.get("termo_busca"),
        "total_bruto": len(anuncios),
        "total_masterprint_petg": len(classificados),
        "produtos": classificados,
    }
