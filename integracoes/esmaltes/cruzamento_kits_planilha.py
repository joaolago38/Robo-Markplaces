"""
integracoes/esmaltes/cruzamento_kits_planilha.py
Cruza cores Impala da planilha com kits mais vendidos no ML → score e kits sugeridos.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from integracoes.esmaltes.analise_anita import _normalizar, extrair_qtd_kit
from integracoes.esmaltes.analise_mercado import extrair_cores_titulo
from integracoes.esmaltes.planilha_impala import cores_impala_disponiveis


def _titulo_norm(kit: dict[str, Any]) -> str:
    return _normalizar(f"{kit.get('titulo') or ''} {kit.get('snippet') or ''}")


def _score_cor_no_kit(produto: dict[str, Any], titulo_norm: str) -> float:
    """
    Pontua se a cor da planilha aparece no título do kit ML.
    Exige match do nome da cor (não só família genérica nude/rosa).
    """
    tokens = [t for t in (produto.get("tokens") or []) if t and len(t) >= 3]
    nome = _normalizar(str(produto.get("nome_cor") or ""))
    if (not tokens and not nome) or not titulo_norm:
        return 0.0
    score = 0.0
    # Nome completo da cor (ex.: "maria cereja") — sinal forte
    if len(nome) >= 4 and nome in titulo_norm:
        score += 5.0
    for tok in tokens:
        if len(tok) < 4:
            continue
        if len(tok) >= 5 and tok in titulo_norm:
            score += 3.0
        elif re.search(rf"\b{re.escape(tok)}\b", titulo_norm):
            score += 2.0
    # Família genérica só reforça se já houve match de token/nome
    if score > 0:
        for familia in extrair_cores_titulo(titulo_norm):
            fam = _normalizar(familia)
            if fam and (fam in nome or nome in fam):
                score += 0.5
                break
    return score


def ranquear_cores_por_demanda_ml(
    kits_ml: list[dict[str, Any]],
    produtos_planilha: list[dict[str, Any]] | None = None,
    *,
    top_kits: int = 40,
) -> list[dict[str, Any]]:
    """
    Para cada cor Impala da planilha, soma vendas dos kits ML em que ela aparece.
    """
    cores = cores_impala_disponiveis(produtos_planilha)
    if not cores:
        return []

    kits_ord = sorted(
        kits_ml or [],
        key=lambda k: int(k.get("quantidade_vendida") or 0),
        reverse=True,
    )[: max(1, top_kits)]

    # sku -> agregados
    agg: dict[str, dict[str, Any]] = {}
    for p in cores:
        sku = str(p.get("sku") or "")
        agg[sku] = {
            "sku": sku,
            "ean": p.get("ean"),
            "nome_cor": p.get("nome_cor"),
            "descricao": p.get("descricao"),
            "tipo": p.get("tipo"),
            "score_demanda": 0.0,
            "vendas_proxy": 0,
            "kits_mencionam": 0,
            "exemplos_kits": [],
        }

    for kit in kits_ord:
        titulo_n = _titulo_norm(kit)
        vendas = int(kit.get("quantidade_vendida") or 0)
        titulo = str(kit.get("titulo") or "")[:70]
        for p in cores:
            sku = str(p.get("sku") or "")
            s = _score_cor_no_kit(p, titulo_n)
            if s <= 0:
                continue
            row = agg[sku]
            row["score_demanda"] += s * (1.0 + vendas / 50.0)
            row["vendas_proxy"] += vendas
            row["kits_mencionam"] += 1
            if len(row["exemplos_kits"]) < 3:
                row["exemplos_kits"].append(
                    {"titulo": titulo, "vendas": vendas, "preco": kit.get("preco")}
                )

    ranked = sorted(
        agg.values(),
        key=lambda r: (float(r["score_demanda"]), int(r["vendas_proxy"]), int(r["kits_mencionam"])),
        reverse=True,
    )
    # só quem teve algum sinal no ML
    com_sinal = [r for r in ranked if float(r["score_demanda"]) > 0]
    return com_sinal if com_sinal else ranked[:20]


def sugerir_kits_por_tamanho(
    cores_rankeadas: list[dict[str, Any]],
    *,
    tamanhos: tuple[int, ...] = (3, 5, 6, 10),
    preco_unitario_ref: float = 8.0,
) -> list[dict[str, Any]]:
    """
    Monta sugestões de kit pegando as cores mais quentes (sem repetir).
    """
    pool = [c for c in cores_rankeadas if float(c.get("score_demanda") or 0) > 0]
    if not pool:
        pool = list(cores_rankeadas)
    sugestoes: list[dict[str, Any]] = []
    usados: set[str] = set()
    for qtd in tamanhos:
        escolhidas: list[dict[str, Any]] = []
        for cor in pool:
            sku = str(cor.get("sku") or "")
            if not sku or sku in usados:
                continue
            escolhidas.append(cor)
            usados.add(sku)
            if len(escolhidas) >= qtd:
                break
        if len(escolhidas) < max(2, qtd // 2):
            continue
        nomes = [str(c.get("nome_cor") or c.get("sku")) for c in escolhidas]
        score_medio = sum(float(c.get("score_demanda") or 0) for c in escolhidas) / len(escolhidas)
        sugestoes.append(
            {
                "qtd": len(escolhidas),
                "nome_sugerido": f"Kit {len(escolhidas)} Impala — " + ", ".join(nomes[:3])
                + ("…" if len(nomes) > 3 else ""),
                "cores": [
                    {
                        "sku": c.get("sku"),
                        "nome_cor": c.get("nome_cor"),
                        "score_demanda": round(float(c.get("score_demanda") or 0), 2),
                    }
                    for c in escolhidas
                ],
                "score_medio": round(score_medio, 2),
                "preco_sugerido_faixa": (
                    f"R$ {len(escolhidas) * preco_unitario_ref * 1.8:.0f}–"
                    f"{len(escolhidas) * preco_unitario_ref * 2.6:.0f}"
                ),
            }
        )
    return sugestoes


def avaliar_kits_cadastrados(
    kits_planilha: list[dict[str, Any]],
    kits_ml: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pontua os 14 kits da planilha conforme demanda nos títulos ML."""
    out: list[dict[str, Any]] = []
    for kit_p in kits_planilha or []:
        tokens = [t for t in (kit_p.get("tokens") or []) if len(t) >= 3]
        nome_n = _normalizar(str(kit_p.get("nome") or ""))
        vendas = 0
        hits = 0
        exemplos: list[str] = []
        for kit_ml in kits_ml or []:
            tit = _titulo_norm(kit_ml)
            if not tit:
                continue
            ok = False
            if any(t in tit for t in tokens if len(t) >= 5):
                ok = True
            # overlap de palavras significativas do nome do kit
            palavras = [w for w in nome_n.split() if len(w) >= 4]
            if palavras and sum(1 for w in palavras if w in tit) >= min(2, len(palavras)):
                ok = True
            if not ok:
                continue
            hits += 1
            vendas += int(kit_ml.get("quantidade_vendida") or 0)
            if len(exemplos) < 2:
                exemplos.append(str(kit_ml.get("titulo") or "")[:60])
        out.append(
            {
                "ordem": kit_p.get("ordem"),
                "nome": kit_p.get("nome"),
                "qtd": kit_p.get("qtd"),
                "hits_ml": hits,
                "vendas_proxy": vendas,
                "demanda": "alta" if hits >= 3 or vendas >= 50 else ("media" if hits >= 1 else "baixa"),
                "exemplos_ml": exemplos,
            }
        )
    return sorted(out, key=lambda x: (int(x.get("vendas_proxy") or 0), int(x.get("hits_ml") or 0)), reverse=True)


def cruzar_planilha_com_mercado(
    kits_ml: list[dict[str, Any]],
    *,
    produtos: list[dict[str, Any]] | None = None,
    kits_cadastrados: list[dict[str, Any]] | None = None,
    top_kits: int = 40,
) -> dict[str, Any]:
    """Pipeline completo de cruzamento. Nunca lança."""
    try:
        from integracoes.esmaltes.planilha_impala import (
            carregar_kits_planilha,
            carregar_produtos_planilha,
        )

        prods = produtos if produtos is not None else carregar_produtos_planilha()
        kits_p = kits_cadastrados if kits_cadastrados is not None else carregar_kits_planilha()
        cores = ranquear_cores_por_demanda_ml(kits_ml, prods, top_kits=top_kits)
        sugestoes = sugerir_kits_por_tamanho(cores)
        kits_aval = avaliar_kits_cadastrados(kits_p, kits_ml)

        # tamanhos mais vendidos no ML
        por_qtd: dict[int, dict[str, Any]] = defaultdict(lambda: {"qtd": 0, "vendas": 0, "anuncios": 0})
        for k in kits_ml or []:
            q = extrair_qtd_kit(str(k.get("titulo") or "")) or int(k.get("qtd_kit") or 0)
            if not q:
                continue
            por_qtd[q]["qtd"] = q
            por_qtd[q]["vendas"] += int(k.get("quantidade_vendida") or 0)
            por_qtd[q]["anuncios"] += 1
        tamanhos = sorted(por_qtd.values(), key=lambda x: x["vendas"], reverse=True)

        return {
            "ok": True,
            "total_cores_planilha": len(cores_impala_disponiveis(prods)),
            "cores_com_demanda": len([c for c in cores if float(c.get("score_demanda") or 0) > 0]),
            "top_cores": cores[:15],
            "kits_sugeridos": sugestoes,
            "kits_cadastrados_avaliados": kits_aval[:10],
            "tamanhos_quentes_ml": tamanhos[:8],
            "total_kits_ml": len(kits_ml or []),
        }
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}
