"""
integracoes/importacao/tendencias_ml_importacao.py
Sinais de demanda no Mercado Livre + viabilidade de importação Alibaba.
"""
from __future__ import annotations

import logging
from typing import Any

from integracoes.alibaba.busca import buscar_oportunidades
from integracoes.importacao.analise_margem import analisar_produto_catalogo, consultar_precos_marketplace

logger = logging.getLogger("tendencias_ml_importacao")

_VEREDITO_LABEL = {
    "importar": "✅ Vale importar",
    "avaliar": "🟡 Avaliar com cautela",
    "nao_vale": "❌ Não vale importar",
    "sem_ml": "⚠️ Sem dados ML",
    "sem_alibaba": "⚠️ Sem cotação Alibaba",
    "sem_dados": "⚠️ Sem dados",
}


def termo_marketplace(produto: dict[str, Any]) -> str:
    for chave in ("termo_marketplace", "termo_busca_pt", "nome"):
        t = str(produto.get(chave) or "").strip()
        if t:
            return t
    return ""


def _score_demanda(
    *,
    total_anuncios: int,
    vendas_totais: int,
    preco_min: float | None,
    preco_max: float | None,
) -> float:
    """Score 0–100: concorrência + volume de vendas no ML."""
    score = 0.0
    if total_anuncios >= 8:
        score += 35
    elif total_anuncios >= 3:
        score += 20
    elif total_anuncios >= 1:
        score += 8

    if vendas_totais >= 500:
        score += 40
    elif vendas_totais >= 100:
        score += 28
    elif vendas_totais >= 20:
        score += 15
    elif vendas_totais > 0:
        score += 6

    if preco_min and preco_max and preco_max > preco_min:
        spread = (preco_max - preco_min) / preco_min
        if spread >= 0.35:
            score += 15
        elif spread >= 0.15:
            score += 8

    return round(min(100.0, score), 1)


def coletar_sinais_ml(produto: dict[str, Any], *, limite: int = 20) -> dict[str, Any]:
    """Demanda e preços no Mercado Livre para o produto."""
    termo = termo_marketplace(produto)
    if not termo:
        return {"ok": False, "motivo": "termo marketplace vazio", "termo": ""}

    from integracoes.ml.ml_client import buscar_concorrentes_por_termo

    limite = max(5, min(40, limite))
    try:
        anuncios = buscar_concorrentes_por_termo(termo, limite=limite)
    except Exception as exc:
        logger.warning("ML tendências importação termo=%r: %s", termo[:50], exc)
        anuncios = []

    precos = [float(a["preco"]) for a in anuncios if float(a.get("preco") or 0) > 0]
    vendas = sum(int(a.get("quantidade_vendida") or 0) for a in anuncios)
    preco_min = round(min(precos), 2) if precos else None
    preco_max = round(max(precos), 2) if precos else None

    score = _score_demanda(
        total_anuncios=len(anuncios),
        vendas_totais=vendas,
        preco_min=preco_min,
        preco_max=preco_max,
    )

    precos_mk = consultar_precos_marketplace(termo, limite=limite)
    if precos_mk.get("ok"):
        preco_min = precos_mk.get("preco_min_brl") or preco_min
        preco_max = precos_mk.get("preco_max_brl") or preco_max

    return {
        "ok": bool(anuncios or precos_mk.get("ok")),
        "termo": termo,
        "total_anuncios": len(anuncios),
        "vendas_totais": vendas,
        "preco_min_brl": preco_min,
        "preco_max_brl": preco_max,
        "preco_mediana_brl": precos_mk.get("preco_mediana_brl"),
        "preco_medio_brl": precos_mk.get("preco_medio_brl"),
        "score_demanda": score,
        "demanda_alta": score >= 45,
        "anuncios": anuncios[:5],
        "precos_marketplace": precos_mk,
    }


def classificar_veredito(
    sinais_ml: dict[str, Any],
    analise: dict[str, Any],
) -> dict[str, Any]:
    """Combina tendência ML + margem de importação."""
    melhor = analise.get("melhor_analise") or {}
    mm = melhor.get("margem_melhor") or {}
    lucro = bool(melhor.get("lucro_razoavel"))
    margem_pct = float(mm.get("margem_pct") or 0)
    margem_brl = float(mm.get("margem_brl") or 0)
    tem_alibaba = bool(analise.get("total_oportunidades"))
    tem_ml = bool(sinais_ml.get("ok") and int(sinais_ml.get("total_anuncios") or 0) > 0)
    demanda_alta = bool(sinais_ml.get("demanda_alta"))

    if not tem_ml and not tem_alibaba:
        codigo = "sem_dados"
    elif not tem_ml:
        codigo = "sem_ml"
    elif not tem_alibaba:
        codigo = "sem_alibaba"
    elif lucro and demanda_alta:
        codigo = "importar"
    elif lucro or (demanda_alta and margem_pct >= 10):
        codigo = "avaliar"
    else:
        codigo = "nao_vale"

    return {
        "codigo": codigo,
        "label": _VEREDITO_LABEL.get(codigo, codigo),
        "lucro_razoavel": lucro,
        "demanda_alta": demanda_alta,
        "margem_pct": margem_pct,
        "margem_brl": margem_brl,
        "score_demanda": sinais_ml.get("score_demanda"),
    }


def analisar_produto_ml_vs_alibaba(
    produto: dict[str, Any],
    *,
    cambio_usd_brl: float,
    pausa_alibaba_seg: float = 1.0,
) -> dict[str, Any]:
    """Pipeline completo: ML (demanda) → Alibaba (cotação) → custo importação → veredito."""
    sinais_ml = coletar_sinais_ml(produto)
    oportunidades = buscar_oportunidades(produto, pausa_seg=pausa_alibaba_seg)
    precos_mk = sinais_ml.get("precos_marketplace") or {}

    analise = analisar_produto_catalogo(
        produto,
        oportunidades,
        cambio_usd_brl=cambio_usd_brl,
    )
    if sinais_ml.get("ok"):
        analise["precos_marketplace"] = precos_mk if precos_mk.get("ok") else sinais_ml
        analise["sinais_ml"] = sinais_ml
    else:
        analise["sinais_ml"] = sinais_ml

    veredito = classificar_veredito(sinais_ml, analise)
    melhor = analise.get("melhor_analise") or {}

    return {
        "ok": True,
        "id": produto.get("id"),
        "produto": produto.get("nome"),
        "termo_marketplace": termo_marketplace(produto),
        "sinais_ml": sinais_ml,
        "total_oportunidades_alibaba": len(oportunidades),
        "analise_importacao": analise,
        "melhor_analise": melhor,
        "veredito": veredito,
        "lucrativas": analise.get("lucrativas", 0),
    }


def consolidar_varredura(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in resultados if r.get("ok")]
    por_veredito: dict[str, list[dict[str, Any]]] = {}
    for r in ok:
        cod = (r.get("veredito") or {}).get("codigo") or "?"
        por_veredito.setdefault(cod, []).append(r)

    importar = sorted(
        por_veredito.get("importar", []),
        key=lambda x: (
            -float((x.get("veredito") or {}).get("margem_pct") or 0),
            -float((x.get("sinais_ml") or {}).get("score_demanda") or 0),
        ),
    )
    avaliar = por_veredito.get("avaliar", [])
    sem_dados = [r for r in ok if (r.get("veredito") or {}).get("codigo") in ("sem_ml", "sem_alibaba", "sem_dados")]

    return {
        "produtos_varridos": len(ok),
        "vale_importar": len(importar),
        "avaliar": len(avaliar),
        "nao_vale": len(por_veredito.get("nao_vale", [])),
        "sem_dados": len(sem_dados),
        "top_importar": importar[:10],
        "top_avaliar": avaliar[:8],
        "todos_sem_dados": len(ok) > 0 and len(sem_dados) == len(ok),
    }


def diagnosticar_coleta_vazia(resultados: list[dict[str, Any]]) -> dict[str, Any] | None:
    ok = [r for r in resultados if r.get("ok")]
    if not ok:
        return None
    sem_ml = sum(1 for r in ok if int((r.get("sinais_ml") or {}).get("total_anuncios") or 0) == 0)
    sem_ali = sum(1 for r in ok if int(r.get("total_oportunidades_alibaba") or 0) == 0)
    if sem_ml < len(ok) or sem_ali < len(ok):
        return None

    from core.ddg_lite import mensagem_circuit_breaker
    from core.prontidao import brave_configurado, ml_configurado

    dicas: list[str] = []
    if ml_configurado():
        dicas.append("API ML `/sites/search` costuma retornar 403 — configure `BRAVE_SEARCH_API_KEY`")
    if brave_configurado():
        dicas.append("Brave autenticou mas retornou 0 — verifique cota/plano da chave")
    else:
        dicas.append("Configure `BRAVE_SEARCH_API_KEY` para busca ML e fallbacks")
    ddg = mensagem_circuit_breaker("ml_busca_termo")
    if ddg:
        dicas.append(ddg)
    dicas.append("Alibaba: scrape/DDG pode falhar em IP de datacenter (GitHub Actions)")

    return {"coleta_vazia": True, "produtos": len(ok), "dicas": dicas}
