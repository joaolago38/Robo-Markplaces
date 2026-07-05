"""
integracoes/esmaltes/analise_anita.py
Análise de anúncios de esmaltes Anita: cores, kits, marcas e margem.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from core.precificacao_comportamento import calcular_lucro_operacao

_MARCAS_ESMALTE: tuple[str, ...] = (
    "anita",
    "impala",
    "risque",
    "colorama",
    "dailus",
    "blant",
    "luigi borni",
    "nati",
    "vult",
    "novo toque",
    "la femme",
    "carmem",
    "top beauty",
    "dote",
)


def _normalizar(texto: str) -> str:
    txt = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in txt if not unicodedata.combining(c))


def detectar_marca(titulo: str) -> str:
    norm = _normalizar(titulo)
    for marca in _MARCAS_ESMALTE:
        if marca in norm:
            return marca.title()
    if "esmalte" in norm or "kit" in norm:
        return "Outros"
    return "Indefinida"


def extrair_qtd_kit(titulo: str) -> int | None:
    norm = _normalizar(titulo)
    for padrao in (
        r"kit\s*(?:com\s*)?(\d{1,2})\b",
        r"(\d{1,2})\s*esmalte",
        r"(\d{1,2})\s*un\b",
        r"c/\s*(\d{1,2})\b",
    ):
        m = re.search(padrao, norm)
        if m:
            try:
                qtd = int(m.group(1))
                if 1 <= qtd <= 50:
                    return qtd
            except (TypeError, ValueError):
                continue
    return None


def _cores_preferencia(produto: dict[str, Any]) -> list[str]:
    if produto.get("tipo") == "cor":
        cor = str(produto.get("cor_preferencia") or "").strip()
        return [cor] if cor else []
    return [str(c).strip() for c in (produto.get("cores_preferencia") or []) if str(c).strip()]


def cores_no_titulo(titulo: str, cores_ref: list[str]) -> list[str]:
    norm = _normalizar(titulo)
    encontradas: list[str] = []
    for cor in cores_ref:
        if _normalizar(cor) in norm:
            encontradas.append(cor)
    return encontradas


def comparar_preferencia(
    produto: dict[str, Any],
    anuncio: dict[str, Any],
) -> dict[str, Any]:
    titulo = str(anuncio.get("titulo") or "")
    preco = float(anuncio.get("preco") or 0)
    meu_preco = float(produto.get("meu_preco") or 0)
    custo = float(produto.get("custo_total") or 0)
    taxa = float(produto.get("taxa_marketplace_pct") or 18)

    cores_ref = _cores_preferencia(produto)
    cores_ok = cores_no_titulo(titulo, cores_ref)
    qtd_detectada = extrair_qtd_kit(titulo)
    qtd_pref = produto.get("qtd_esmaltes_preferencia")

    diff_preco_pct = None
    if meu_preco > 0 and preco > 0:
        diff_preco_pct = round((preco - meu_preco) / meu_preco * 100, 1)

    diff_qtd = None
    if qtd_pref is not None and qtd_detectada is not None:
        diff_qtd = qtd_detectada - int(qtd_pref)

    cores_faltando = [c for c in cores_ref if c not in cores_ok]
    margem_meu = calcular_lucro_operacao(meu_preco, custo, taxa) if meu_preco > 0 else {}
    margem_anuncio = calcular_lucro_operacao(preco, custo, taxa) if preco > 0 and custo > 0 else {}

    kit_ok = True
    if produto.get("tipo") == "kit" and qtd_pref is not None and qtd_detectada is not None:
        kit_ok = qtd_detectada == int(qtd_pref)

    cor_ok = True
    if produto.get("tipo") == "cor" and cores_ref:
        cor_ok = bool(cores_ok)

    return {
        "marca_detectada": detectar_marca(titulo),
        "qtd_kit_detectada": qtd_detectada,
        "qtd_kit_preferencia": qtd_pref,
        "diff_qtd_kit": diff_qtd,
        "kit_conforme_preferencia": kit_ok,
        "cores_encontradas": cores_ok,
        "cores_faltando": cores_faltando,
        "cor_conforme_preferencia": cor_ok,
        "diff_preco_pct": diff_preco_pct,
        "meu_preco": meu_preco,
        "preco_anuncio": preco,
        "margem_meu": margem_meu,
        "margem_anuncio": margem_anuncio,
        "conforme_preferencia": kit_ok and cor_ok,
    }


def ranking_marcas(anuncios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totais: dict[str, dict[str, Any]] = {}
    for an in anuncios:
        marca = detectar_marca(str(an.get("titulo") or ""))
        vendidos = int(an.get("quantidade_vendida") or 0)
        preco = float(an.get("preco") or 0)
        bucket = totais.setdefault(marca, {"marca": marca, "vendidos": 0, "anuncios": 0, "preco_medio": 0.0, "_precos": []})
        bucket["vendidos"] += max(0, vendidos)
        bucket["anuncios"] += 1
        if preco > 0:
            bucket["_precos"].append(preco)

    ranking: list[dict[str, Any]] = []
    for item in totais.values():
        precos = item.pop("_precos", [])
        if precos:
            item["preco_medio"] = round(sum(precos) / len(precos), 2)
        ranking.append(item)

    ranking.sort(key=lambda x: (x["vendidos"], x["anuncios"]), reverse=True)
    return ranking


def analisar_produto(
    produto: dict[str, Any],
    anuncios: list[dict[str, Any]],
) -> dict[str, Any]:
    analises: list[dict[str, Any]] = []
    for an in anuncios:
        comp = comparar_preferencia(produto, an)
        analises.append({**an, **comp})

    anita = [a for a in analises if _normalizar(a.get("marca_detectada", "")) == "anita"]
    ranking = ranking_marcas(anuncios)
    marca_lider = ranking[0]["marca"] if ranking else "n/d"

    precos_anita = [float(a.get("preco") or 0) for a in anita if float(a.get("preco") or 0) > 0]
    menor_anita = min(precos_anita) if precos_anita else None
    meu_preco = float(produto.get("meu_preco") or 0)
    custo = float(produto.get("custo_total") or 0)
    taxa = float(produto.get("taxa_marketplace_pct") or 18)
    margem_minha = calcular_lucro_operacao(meu_preco, custo, taxa) if meu_preco > 0 else {}

    divergencias_kit = [
        a for a in analises if a.get("diff_qtd_kit") not in (None, 0) and a.get("marca_detectada") == "Anita"
    ]
    divergencias_cor = [
        a for a in analises if a.get("cores_faltando") and a.get("marca_detectada") == "Anita"
    ]

    impala_anuncios = [a for a in analises if _normalizar(a.get("marca_detectada", "")) == "impala"]
    unidades_impala = sum(int(a.get("quantidade_vendida") or 0) for a in impala_anuncios)
    unidades_anita = sum(int(a.get("quantidade_vendida") or 0) for a in anita)
    total_unidades_marcas = unidades_impala + unidades_anita
    share_impala_pct = (
        round(100.0 * unidades_impala / total_unidades_marcas, 1) if total_unidades_marcas > 0 else None
    )
    precos_impala = [float(a.get("preco") or 0) for a in impala_anuncios if float(a.get("preco") or 0) > 0]
    menor_impala = min(precos_impala) if precos_impala else None
    preco_medio_impala = round(sum(precos_impala) / len(precos_impala), 2) if precos_impala else None

    posicao_impala = None
    for i, item in enumerate(ranking, start=1):
        if _normalizar(str(item.get("marca") or "")) == "impala":
            posicao_impala = i
            break

    impala_lider = _normalizar(marca_lider) == "impala"
    diff_preco_impala_vs_meu = None
    if meu_preco > 0 and menor_impala:
        diff_preco_impala_vs_meu = round((float(menor_impala) - meu_preco) / meu_preco * 100, 1)

    return {
        "id": produto.get("id"),
        "nome": produto.get("nome"),
        "tipo": produto.get("tipo"),
        "termo_busca": produto.get("termo_busca"),
        "meu_preco": meu_preco,
        "custo_total": custo,
        "total_anuncios": len(anuncios),
        "total_anita": len(anita),
        "total_impala": len(impala_anuncios),
        "unidades_vendidas_impala": unidades_impala,
        "unidades_vendidas_anita": unidades_anita,
        "share_impala_pct": share_impala_pct,
        "menor_preco_impala": menor_impala,
        "preco_medio_impala": preco_medio_impala,
        "posicao_impala_ranking": posicao_impala,
        "impala_lider_vendas": impala_lider,
        "diff_preco_impala_vs_meu_pct": diff_preco_impala_vs_meu,
        "ranking_marcas": ranking,
        "marca_mais_vendida": marca_lider,
        "menor_preco_anita": menor_anita,
        "margem_minha": margem_minha,
        "analises": analises,
        "divergencias_kit": len(divergencias_kit),
        "divergencias_cor": len(divergencias_cor),
    }
