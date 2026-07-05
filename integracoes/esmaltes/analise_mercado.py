"""
integracoes/esmaltes/analise_mercado.py
Análise ampla do mercado de esmaltes no ML: cores, kits, margem viável e propostas de competição.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from core.precificacao_comportamento import calcular_lucro_operacao, calcular_preco_piso
from integracoes.esmaltes.analise_anita import (
    _normalizar,
    detectar_marca,
    extrair_qtd_kit,
)

_CORES_ESMALTE: tuple[str, ...] = (
    "nude",
    "bege",
    "rosa",
    "pink",
    "vermelho",
    "vinho",
    "marsala",
    "preto",
    "branco",
    "azul",
    "verde",
    "roxo",
    "lilas",
    "lilás",
    "coral",
    "laranja",
    "amarelo",
    "dourado",
    "prata",
    "glitter",
    "perolado",
    "creme",
    "pastel",
    "neon",
    "candy",
    "chocolate",
    "cafe",
    "café",
    "marrom",
    "terracota",
    "bailarina",
    "avoante",
    "sortido",
    "sortida",
    "classico",
    "clássico",
    "classicos",
    "clássicos",
    "moda",
    "neon",
    "francesinha",
)

_TERMOS_KIT: tuple[str, ...] = (
    "kit",
    "combo",
    "c/ ",
    "com ",
    "pack",
    "atacado",
    "conjunto",
)


def extrair_cores_titulo(titulo: str) -> list[str]:
    norm = _normalizar(titulo)
    encontradas: list[str] = []
    for cor in _CORES_ESMALTE:
        c_norm = _normalizar(cor)
        if c_norm in norm and cor not in encontradas:
            encontradas.append(cor.title() if cor != "lilás" else "Lilás")
    return encontradas


def classificar_tipo_anuncio(titulo: str, qtd_kit: int | None) -> str:
    norm = _normalizar(titulo)
    if qtd_kit and qtd_kit >= 2:
        return "kit"
    if any(t in norm for t in _TERMOS_KIT):
        return "kit"
    if "esmalte" in norm:
        return "unitario"
    return "outro"


def classificar_anuncio(anuncio: dict[str, Any]) -> dict[str, Any]:
    titulo = str(anuncio.get("titulo") or "")
    preco = float(anuncio.get("preco") or 0)
    qtd = extrair_qtd_kit(titulo)
    cores = extrair_cores_titulo(titulo)
    tipo = classificar_tipo_anuncio(titulo, qtd)
    preco_por_un = round(preco / qtd, 2) if qtd and qtd > 0 and preco > 0 else None

    return {
        **anuncio,
        "marca": detectar_marca(titulo),
        "qtd_kit": qtd,
        "tipo_anuncio": tipo,
        "cores_detectadas": cores,
        "preco_por_unidade": preco_por_un,
        "descricao_kit": _descrever_kit(titulo, qtd, cores, detectar_marca(titulo)),
    }


def _descrever_kit(titulo: str, qtd: int | None, cores: list[str], marca: str) -> str:
    partes: list[str] = []
    if qtd:
        partes.append(f"{qtd} esmalte(s)")
    elif classificar_tipo_anuncio(titulo, qtd) == "unitario":
        partes.append("unitário")
    if cores:
        partes.append("cores: " + ", ".join(cores[:5]))
    if marca and marca not in ("Indefinida", "Outros"):
        partes.append(f"marca {marca}")
    return " | ".join(partes) if partes else "formato não identificado"


def _margem_minima_produto(produto: dict[str, Any] | None, fallback: float) -> float:
    if not produto:
        return fallback
    from core.config import MARGEM_FASE_1_PCT, MARGEM_FASE_2_PCT, MARGEM_FASE_3_PCT

    fase = str(produto.get("fase_atual") or "1").strip()
    if fase == "3":
        return MARGEM_FASE_3_PCT
    if fase == "2":
        return MARGEM_FASE_2_PCT
    return MARGEM_FASE_1_PCT


def margem_em_preco(
    preco: float,
    custo: float,
    taxa_pct: float,
    margem_min_pct: float,
) -> dict[str, Any]:
    lucro = calcular_lucro_operacao(preco, custo, taxa_pct)
    margem = float(lucro.get("margem_operacional_pct") or 0)
    return {
        **lucro,
        "margem_satisfatoria": margem >= margem_min_pct,
        "margem_minima_pct": margem_min_pct,
        "preco_piso": round(calcular_preco_piso(custo, taxa_pct, margem_min_pct), 2),
    }


def padroes_kits(anuncios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, dict[str, Any]] = {}
    for an in anuncios:
        qtd = an.get("qtd_kit")
        if not qtd or int(qtd) < 2:
            continue
        q = int(qtd)
        b = buckets.setdefault(q, {"qtd": q, "anuncios": 0, "vendidos": 0, "preco_medio": 0.0, "_precos": []})
        b["anuncios"] += 1
        b["vendidos"] += int(an.get("quantidade_vendida") or 0)
        preco = float(an.get("preco") or 0)
        if preco > 0:
            b["_precos"].append(preco)

    saida: list[dict[str, Any]] = []
    for item in buckets.values():
        precos = item.pop("_precos", [])
        if precos:
            item["preco_medio"] = round(sum(precos) / len(precos), 2)
        saida.append(item)
    saida.sort(key=lambda x: (x["vendidos"], x["anuncios"]), reverse=True)
    return saida


def tendencia_cores(anuncios: list[dict[str, Any]], top_n: int = 8) -> list[dict[str, Any]]:
    pesos: Counter[str] = Counter()
    for an in anuncios:
        vendas = max(1, int(an.get("quantidade_vendida") or 0))
        for cor in an.get("cores_detectadas") or extrair_cores_titulo(str(an.get("titulo") or "")):
            pesos[cor] += vendas
    return [{"cor": cor, "peso_vendas": peso} for cor, peso in pesos.most_common(top_n)]


def ranking_marcas_mercado(anuncios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totais: dict[str, dict[str, Any]] = {}
    for an in anuncios:
        marca = str(an.get("marca") or detectar_marca(str(an.get("titulo") or "")))
        vendidos = int(an.get("quantidade_vendida") or 0)
        preco = float(an.get("preco") or 0)
        bucket = totais.setdefault(
            marca,
            {"marca": marca, "vendidos": 0, "anuncios": 0, "preco_medio": 0.0, "_precos": []},
        )
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


def _referencia_segmento(
    segmento: dict[str, Any],
    produtos_por_sku: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    sku = str(segmento.get("sku_referencia") or "").strip()
    if not sku:
        return None
    produto = produtos_por_sku.get(sku)
    if not produto:
        return None

    taxa = float(segmento.get("taxa_marketplace_pct") or 18)
    custo = float(produto.get("custo_total") or 0)
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    meu_preco = float(ml.get("preco") or produto.get("preco") or 0)
    margem_min = float(segmento.get("margem_minima_pct") or _margem_minima_produto(produto, 18))

    return {
        "sku": sku,
        "nome": produto.get("nome"),
        "custo_total": custo,
        "meu_preco": meu_preco,
        "taxa_marketplace_pct": taxa,
        "margem_minima_pct": margem_min,
        "fase_atual": produto.get("fase_atual"),
        "titulo_ml": ml.get("titulo_anuncio") or produto.get("nome"),
        "qtd_esmaltes_catalogo": _qtd_do_nome(str(produto.get("nome") or "")),
    }


def _qtd_do_nome(nome: str) -> int | None:
    m = re.search(r"kit\s*(\d{1,2})", _normalizar(nome))
    if m:
        return int(m.group(1))
    return None


def listar_oportunidades_margem(
    anuncios: list[dict[str, Any]],
    referencia: dict[str, Any],
    *,
    vendas_min: int = 5,
    abaixo_concorrente_pct: float = 2.0,
) -> list[dict[str, Any]]:
    custo = float(referencia.get("custo_total") or 0)
    taxa = float(referencia.get("taxa_marketplace_pct") or 18)
    margem_min = float(referencia.get("margem_minima_pct") or 18)
    if custo <= 0:
        return []

    candidatos = sorted(
        [a for a in anuncios if float(a.get("preco") or 0) > 0],
        key=lambda x: int(x.get("quantidade_vendida") or 0),
        reverse=True,
    )

    oportunidades: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for an in candidatos:
        item_id = str(an.get("item_id") or an.get("titulo") or "")
        if item_id in vistos:
            continue
        vistos.add(item_id)

        vendas = int(an.get("quantidade_vendida") or 0)
        if vendas < vendas_min:
            continue

        preco_conc = float(an.get("preco") or 0)
        preco_alvo = round(preco_conc * (1 - abaixo_concorrente_pct / 100.0), 2)
        diag = margem_em_preco(preco_alvo, custo, taxa, margem_min)
        if not diag.get("margem_satisfatoria"):
            continue

        oportunidades.append(
            {
                "item_id": an.get("item_id"),
                "titulo": an.get("titulo"),
                "marca": an.get("marca"),
                "preco_concorrente": preco_conc,
                "preco_alvo": preco_alvo,
                "quantidade_vendida": vendas,
                "qtd_kit": an.get("qtd_kit"),
                "cores_detectadas": an.get("cores_detectadas") or [],
                "descricao_kit": an.get("descricao_kit"),
                "frete_gratis": an.get("frete_gratis"),
                "margem": diag,
            }
        )
    return oportunidades


def gerar_propostas_competir(
    segmento: dict[str, Any],
    anuncios: list[dict[str, Any]],
    referencia: dict[str, Any] | None,
    *,
    vendas_min: int = 5,
    abaixo_concorrente_pct: float = 2.0,
) -> list[dict[str, Any]]:
    propostas: list[dict[str, Any]] = []
    classificados = [classificar_anuncio(a) for a in anuncios]
    kits = padroes_kits(classificados)
    cores = tendencia_cores(classificados)
    ranking = ranking_marcas_mercado(classificados)
    seg_id = str(segmento.get("id") or "?")
    seg_nome = str(segmento.get("nome") or seg_id)

    if kits:
        lider = kits[0]
        propostas.append(
            {
                "prioridade": "media",
                "tipo": "kit",
                "segmento_id": seg_id,
                "texto": (
                    f"*{seg_nome}*: kits de {lider['qtd']} un lideram vendas "
                    f"({lider['vendidos']} vendidos, média R$ {lider['preco_medio']:.2f})"
                ),
            }
        )

    if cores:
        top_cores = ", ".join(c["cor"] for c in cores[:4])
        propostas.append(
            {
                "prioridade": "media",
                "tipo": "cores",
                "segmento_id": seg_id,
                "texto": f"*{seg_nome}*: cores em alta — {top_cores}",
                "cores_tendencia": [c["cor"] for c in cores[:6]],
            }
        )

    if ranking:
        lider_marca = ranking[0]
        propostas.append(
            {
                "prioridade": "baixa",
                "tipo": "marca",
                "segmento_id": seg_id,
                "texto": (
                    f"*{seg_nome}*: {lider_marca['marca']} lidera com "
                    f"{lider_marca['vendidos']} vendas (média R$ {lider_marca.get('preco_medio', 0):.2f})"
                ),
            }
        )

    if not referencia:
        return propostas

    sku = referencia.get("sku", "?")
    meu_preco = float(referencia.get("meu_preco") or 0)
    custo = float(referencia.get("custo_total") or 0)
    taxa = float(referencia.get("taxa_marketplace_pct") or 18)
    margem_min = float(referencia.get("margem_minima_pct") or 18)

    oportunidades = listar_oportunidades_margem(
        classificados,
        referencia,
        vendas_min=vendas_min,
        abaixo_concorrente_pct=abaixo_concorrente_pct,
    )

    for op in oportunidades[:3]:
        margem = op.get("margem") or {}
        propostas.append(
            {
                "prioridade": "alta",
                "tipo": "preco",
                "segmento_id": seg_id,
                "sku": sku,
                "texto": (
                    f"Competir com *{sku}* em R$ {op['preco_alvo']:.2f} "
                    f"(−{abaixo_concorrente_pct:.0f}% vs {op['preco_concorrente']:.2f}, "
                    f"{op['quantidade_vendida']} vendas) — margem {margem.get('margem_operacional_pct')}%"
                ),
                "preco_sugerido": op["preco_alvo"],
                "margem_pct": margem.get("margem_operacional_pct"),
                "concorrente": op,
            }
        )

    # Cores que vendem mas não aparecem no seu título
    titulo_meu = str(referencia.get("titulo_ml") or "")
    minhas_cores = {c.lower() for c in extrair_cores_titulo(titulo_meu)}
    faltando = [c["cor"] for c in cores if c["cor"].lower() not in minhas_cores][:3]
    if faltando:
        propostas.append(
            {
                "prioridade": "media",
                "tipo": "cores",
                "segmento_id": seg_id,
                "sku": sku,
                "texto": f"Incluir no anúncio *{sku}* cores em alta: {', '.join(faltando)}",
                "cores_sugeridas": faltando,
            }
        )

    # Kit size mismatch
    qtd_ref = segmento.get("qtd_esmaltes_referencia") or referencia.get("qtd_esmaltes_catalogo")
    if kits and qtd_ref:
        qtd_lider = int(kits[0]["qtd"])
        if qtd_lider != int(qtd_ref):
            propostas.append(
                {
                    "prioridade": "media",
                    "tipo": "kit",
                    "segmento_id": seg_id,
                    "sku": sku,
                    "texto": (
                        f"Mercado prefere kit {qtd_lider} un (seu catálogo: {qtd_ref}) — "
                        f"avalie bundle ou novo SKU"
                    ),
                }
            )

    # Se está caro vs menor concorrente com vendas
    com_vendas = [a for a in classificados if int(a.get("quantidade_vendida") or 0) >= vendas_min]
    if com_vendas and meu_preco > 0:
        menor = min(com_vendas, key=lambda x: float(x.get("preco") or 999999))
        menor_preco = float(menor.get("preco") or 0)
        if menor_preco > 0 and meu_preco > menor_preco * 1.03:
            diag = margem_em_preco(
                round(menor_preco * (1 - abaixo_concorrente_pct / 100.0), 2),
                custo,
                taxa,
                margem_min,
            )
            if diag.get("margem_satisfatoria"):
                propostas.append(
                    {
                        "prioridade": "alta",
                        "tipo": "preco",
                        "segmento_id": seg_id,
                        "sku": sku,
                        "texto": (
                            f"Seu *{sku}* a R$ {meu_preco:.2f} está acima do líder "
                            f"(R$ {menor_preco:.2f}) — teste R$ {diag.get('preco_piso', menor_preco):.2f} "
                            f"com margem {diag.get('margem_operacional_pct')}%"
                        ),
                        "preco_sugerido": round(menor_preco * (1 - abaixo_concorrente_pct / 100.0), 2),
                        "margem_pct": diag.get("margem_operacional_pct"),
                    }
                )
            else:
                piso = diag.get("preco_piso") or calcular_preco_piso(custo, taxa, margem_min)
                propostas.append(
                    {
                        "prioridade": "media",
                        "tipo": "preco",
                        "segmento_id": seg_id,
                        "sku": sku,
                        "texto": (
                            f"Líder a R$ {menor_preco:.2f} abaixo do seu piso — "
                            f"mínimo viável *{sku}*: R$ {piso:.2f}"
                        ),
                        "preco_sugerido": piso,
                    }
                )

    # Frete grátis nos líderes
    lideres_frete = [a for a in com_vendas if a.get("frete_gratis")][:2]
    if lideres_frete:
        propostas.append(
            {
                "prioridade": "baixa",
                "tipo": "frete",
                "segmento_id": seg_id,
                "texto": (
                    f"Concorrentes com frete grátis lideram em *{seg_nome}* — "
                    "revise embalagem/frete no preço"
                ),
            }
        )

    # dedupe por texto similar
    vistas: set[str] = set()
    unicas: list[dict[str, Any]] = []
    for p in propostas:
        chave = p.get("texto", "")[:80]
        if chave in vistas:
            continue
        vistas.add(chave)
        unicas.append(p)

    ordem = {"alta": 0, "media": 1, "baixa": 2}
    unicas.sort(key=lambda x: ordem.get(str(x.get("prioridade")), 9))
    return unicas


def analisar_segmento(
    segmento: dict[str, Any],
    anuncios: list[dict[str, Any]],
    produtos_por_sku: dict[str, dict[str, Any]],
    *,
    vendas_min: int = 5,
    abaixo_concorrente_pct: float = 2.0,
) -> dict[str, Any]:
    classificados = [classificar_anuncio(a) for a in anuncios]
    referencia = _referencia_segmento(segmento, produtos_por_sku)
    kits = padroes_kits(classificados)
    cores = tendencia_cores(classificados)
    ranking = ranking_marcas_mercado(classificados)
    oportunidades = (
        listar_oportunidades_margem(
            classificados,
            referencia,
            vendas_min=vendas_min,
            abaixo_concorrente_pct=abaixo_concorrente_pct,
        )
        if referencia
        else []
    )
    propostas = gerar_propostas_competir(
        segmento,
        anuncios,
        referencia,
        vendas_min=vendas_min,
        abaixo_concorrente_pct=abaixo_concorrente_pct,
    )

    destaques = sorted(
        classificados,
        key=lambda x: int(x.get("quantidade_vendida") or 0),
        reverse=True,
    )[:6]

    return {
        "id": segmento.get("id"),
        "nome": segmento.get("nome"),
        "termo_busca": segmento.get("termo_busca"),
        "prioridade": int(segmento.get("prioridade") or 99),
        "referencia": referencia,
        "total_anuncios": len(classificados),
        "padroes_kits": kits,
        "tendencia_cores": cores,
        "ranking_marcas": ranking,
        "oportunidades_margem": oportunidades,
        "propostas": propostas,
        "destaques": destaques,
        "ok": True,
    }


def consolidar_mercado(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrega anúncios únicos e propostas de todos os segmentos."""
    por_item: dict[str, dict[str, Any]] = {}
    todas_propostas: list[dict[str, Any]] = []
    ranking_global: dict[str, int] = {}

    for seg in resultados:
        if not seg.get("ok"):
            continue
        for prop in seg.get("propostas") or []:
            todas_propostas.append(prop)
        for marca in seg.get("ranking_marcas") or []:
            m = str(marca.get("marca") or "?")
            ranking_global[m] = ranking_global.get(m, 0) + int(marca.get("vendidos") or 0)
        for dest in seg.get("destaques") or []:
            iid = str(dest.get("item_id") or "")
            if not iid:
                continue
            atual = por_item.get(iid)
            vendas = int(dest.get("quantidade_vendida") or 0)
            if not atual or vendas > int(atual.get("quantidade_vendida") or 0):
                por_item[iid] = dest

    anuncios_unicos = list(por_item.values())
    anuncios_unicos.sort(key=lambda x: int(x.get("quantidade_vendida") or 0), reverse=True)

    ordem = {"alta": 0, "media": 1, "baixa": 2}
    propostas_unicas: list[dict[str, Any]] = []
    vistas: set[str] = set()
    for p in sorted(todas_propostas, key=lambda x: ordem.get(str(x.get("prioridade")), 9)):
        chave = str(p.get("texto", ""))[:100]
        if chave in vistas:
            continue
        vistas.add(chave)
        propostas_unicas.append(p)

    ranking_ord = sorted(ranking_global.items(), key=lambda x: x[1], reverse=True)

    return {
        "total_anuncios_unicos": len(anuncios_unicos),
        "total_segmentos": len([r for r in resultados if r.get("ok")]),
        "ranking_marcas_global": [{"marca": m, "vendidos": v} for m, v in ranking_ord[:8]],
        "top_anuncios": anuncios_unicos[:12],
        "propostas": propostas_unicas,
        "total_oportunidades_margem": sum(len(s.get("oportunidades_margem") or []) for s in resultados),
    }
