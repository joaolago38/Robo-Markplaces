"""
integracoes/escritorio/analise_masterprint_escritorio.py
Varredura: pincéis recarregáveis e apagadores Masterprint no Mercado Livre.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from integracoes.escritorio.custos_masterprint_escritorio import (
    carregar_tabela_custos,
    detectar_cor,
    detectar_qtd_embalagem,
    detectar_tipo,
    enriquecer_com_margem,
    top_por_margem,
)

MARCA_ALVO = "Masterprint"

_RE_ESPACO = re.compile(r"\s+")


def _norm(texto: str) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _RE_ESPACO.sub(" ", s.lower()).strip()


def _eh_masterprint(titulo: str) -> bool:
    n = _norm(titulo)
    return "masterprint" in n or "master print" in n or "mp-616" in n or "mp-619" in n or "mp-3100" in n


def _eh_produto_alvo(titulo: str, tipo_esperado: str | None = None) -> bool:
    n = _norm(titulo)
    tipo = detectar_tipo(titulo)
    if not tipo:
        return False
    if tipo_esperado and tipo != tipo_esperado:
        return False
    if tipo == "apagador":
        return "apagador" in n
    # pincéis: preferir recarregável; aceita MP-616/619 mesmo sem a palavra
    if "recarreg" in n or "mp-616" in n or "mp-619" in n:
        return True
    # listagens Masterprint de pincel/marcador sem a palavra ainda entram
    return "pincel" in n or "marcador" in n


def classificar_masterprint_escritorio(
    anuncio: dict[str, Any],
    *,
    tipo_esperado: str | None = None,
) -> dict[str, Any] | None:
    titulo = str(anuncio.get("titulo") or "")
    if not _eh_masterprint(titulo):
        return None
    if not _eh_produto_alvo(titulo, tipo_esperado):
        return None
    tipo = tipo_esperado or detectar_tipo(titulo)
    if not tipo:
        return None
    n = _norm(titulo)
    if tipo.startswith("pincel") and ("nao recarreg" in n or "nao-recarreg" in n):
        return None

    preco = float(anuncio.get("preco") or anuncio.get("price") or 0)
    vendidos = int(anuncio.get("quantidade_vendida") or anuncio.get("sold_quantity") or 0)
    return {
        "item_id": str(anuncio.get("item_id") or anuncio.get("id") or ""),
        "titulo": titulo[:140],
        "preco": preco,
        "quantidade_vendida": max(0, vendidos),
        "marca": MARCA_ALVO,
        "tipo": tipo,
        "cor": detectar_cor(titulo),
        "qtd_embalagem": detectar_qtd_embalagem(titulo),
        "receita_proxy": round(preco * max(0, vendidos), 2),
        "permalink": anuncio.get("permalink") or anuncio.get("url") or "",
        "marketplace": anuncio.get("marketplace") or "mercadolivre",
    }


def deduplicar(produtos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    por_id: dict[str, dict[str, Any]] = {}
    for p in produtos:
        iid = str(p.get("item_id") or "").strip()
        chave = iid or f"{p.get('titulo')}|{p.get('preco')}"
        atual = por_id.get(chave)
        if atual is None:
            por_id[chave] = dict(p)
            continue
        if int(p.get("quantidade_vendida") or 0) > int(atual.get("quantidade_vendida") or 0):
            por_id[chave] = dict(p)
        elif float(p.get("receita_proxy") or 0) > float(atual.get("receita_proxy") or 0):
            por_id[chave] = dict(p)
    return list(por_id.values())


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


def consolidar_masterprint_escritorio(
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
    ref = tabela.get("custos_referencia") or {}

    por_tipo: dict[str, int] = {}
    for p in unicos:
        t = str(p.get("tipo") or "?")
        por_tipo[t] = por_tipo.get(t, 0) + 1

    return {
        "ok": True,
        "marca": MARCA_ALVO,
        "escopo": "pinceis_recarregaveis_e_apagadores",
        "total_anuncios_ativos": len(unicos),
        "por_tipo": por_tipo,
        "preco_min": round(min(precos), 2) if precos else 0.0,
        "preco_max": round(max(precos), 2) if precos else 0.0,
        "preco_medio": round(sum(precos) / len(precos), 2) if precos else 0.0,
        "custos_referencia": ref,
        "tabela_custos": tabela.get("tabela"),
        "tabela_valida_em": tabela.get("valida_a_partir_de"),
        "margem_media_brl": round(sum(margens) / len(margens), 2) if margens else None,
        "lucro_proxy_total": round(sum(float(p.get("lucro_proxy") or 0) for p in unicos), 2),
        "receita_proxy_total": round(sum(float(p.get("receita_proxy") or 0) for p in unicos), 2),
        "vendas_totais": sum(int(p.get("quantidade_vendida") or 0) for p in unicos),
        "mais_rentaveis": top_por_margem(unicos, top_n=top_n),
        "mais_vendidos": top_vendas(unicos, top_n=top_n),
        "maior_ganho": calcular_maiores_ganhos(unicos, produtos_anteriores, top_n=top_n),
        "produtos": unicos,
        "termos_varridos": sum(1 for r in resultados_termos if r.get("ok")),
    }


def processar_termo_escritorio(
    segmento: dict[str, Any],
    anuncios: list[dict[str, Any]],
) -> dict[str, Any]:
    tipo_esp = str(segmento.get("tipo") or "").strip() or None
    classificados: list[dict[str, Any]] = []
    for a in anuncios:
        item = classificar_masterprint_escritorio(a, tipo_esperado=tipo_esp)
        if item:
            classificados.append(item)
    return {
        "ok": True,
        "id": segmento.get("id"),
        "nome": segmento.get("nome"),
        "termo_busca": segmento.get("termo_busca"),
        "tipo": tipo_esp,
        "total_bruto": len(anuncios),
        "total_classificados": len(classificados),
        "produtos": classificados,
    }
