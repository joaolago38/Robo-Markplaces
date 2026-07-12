"""
integracoes/comparativo/ml_shopee_categorias.py
Compara atratividade comercial ML × Shopee para categorias (esmaltes, filamentos).

Shopee competitiva não expõe vendas públicas neste projeto — o volume Shopee
usa proxy (anúncios × cobertura de preço) e o veredito deixa isso explícito.
"""
from __future__ import annotations

import statistics
from typing import Any

MARKETPLACES = ("mercadolivre", "shopee")

_LABELS = {
    "mercadolivre": "Mercado Livre",
    "shopee": "Shopee",
}

_TOKENS_CATEGORIA: dict[str, tuple[str, ...]] = {
    "esmalte": ("esmalte", "manicure", "anita", "impala", "kit", "unha"),
    "filamento": ("filamento", "pla", "petg", "abs", "impressora", "3d", "filament"),
}

# Densidade 25% | Volume 35% | Preço 20% | Cobertura preço 20%
_PESOS = {
    "densidade": 0.25,
    "volume": 0.35,
    "preco": 0.20,
    "cobertura": 0.20,
}


def label_marketplace(mp: str) -> str:
    return _LABELS.get(mp, mp.title())


def tokens_categoria(categoria: str) -> tuple[str, ...]:
    return _TOKENS_CATEGORIA.get((categoria or "").strip().lower(), ())


def _precos_positivos(anuncios: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for a in anuncios:
        try:
            p = float(a.get("preco") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0:
            out.append(p)
    return out


def _metricas_marketplace(anuncios: list[dict[str, Any]], marketplace: str) -> dict[str, Any]:
    subset = [a for a in anuncios if str(a.get("marketplace") or "") == marketplace]
    n = len(subset)
    precos = _precos_positivos(subset)
    com_preco = len(precos)
    cobertura = (com_preco / n) if n else 0.0
    vendidos = 0
    for a in subset:
        try:
            vendidos += int(a.get("quantidade_vendida") or 0)
        except (TypeError, ValueError):
            continue

    if marketplace == "shopee":
        # Sem sold_quantity público: proxy proporcional à densidade com preço
        volume_sinal = float(n) * cobertura
        volume_eh_proxy = True
    else:
        volume_sinal = float(vendidos) if vendidos > 0 else float(n) * cobertura
        volume_eh_proxy = vendidos <= 0

    mediana = float(statistics.median(precos)) if precos else 0.0
    media = round(sum(precos) / len(precos), 2) if precos else 0.0

    return {
        "marketplace": marketplace,
        "label": label_marketplace(marketplace),
        "anuncios": n,
        "com_preco": com_preco,
        "cobertura_preco": round(cobertura, 4),
        "vendidos": vendidos,
        "volume_sinal": round(volume_sinal, 4),
        "volume_eh_proxy": volume_eh_proxy,
        "preco_mediana": round(mediana, 2),
        "preco_medio": media,
        "preco_min": round(min(precos), 2) if precos else 0.0,
        "preco_max": round(max(precos), 2) if precos else 0.0,
    }


def _norm_maior_melhor(valores: dict[str, float]) -> dict[str, float]:
    mx = max(valores.values()) if valores else 0.0
    if mx <= 0:
        return {k: 0.0 for k in valores}
    return {k: round(v / mx, 4) for k, v in valores.items()}


def _norm_menor_melhor(valores: dict[str, float]) -> dict[str, float]:
    """Preço menor = score maior. Marketplaces sem preço recebem 0."""
    positivos = {k: v for k, v in valores.items() if v > 0}
    if not positivos:
        return {k: 0.0 for k in valores}
    menor = min(positivos.values())
    out: dict[str, float] = {}
    for k, v in valores.items():
        if v <= 0:
            out[k] = 0.0
        else:
            out[k] = round(menor / v, 4)
    return out


def _calcular_scores(metricas: dict[str, dict[str, Any]]) -> dict[str, float]:
    dens = _norm_maior_melhor({mp: float(m.get("anuncios") or 0) for mp, m in metricas.items()})
    vol = _norm_maior_melhor({mp: float(m.get("volume_sinal") or 0) for mp, m in metricas.items()})
    preco = _norm_menor_melhor({mp: float(m.get("preco_mediana") or 0) for mp, m in metricas.items()})
    cob = {mp: float(m.get("cobertura_preco") or 0) for mp, m in metricas.items()}

    scores: dict[str, float] = {}
    for mp in metricas:
        scores[mp] = round(
            _PESOS["densidade"] * dens.get(mp, 0)
            + _PESOS["volume"] * vol.get(mp, 0)
            + _PESOS["preco"] * preco.get(mp, 0)
            + _PESOS["cobertura"] * cob.get(mp, 0),
            4,
        )
    return scores


def analisar_termo(
    segmento: dict[str, Any],
    anuncios: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analisa um termo do catálogo com anúncios já coletados (ML + Shopee)."""
    metricas = {mp: _metricas_marketplace(anuncios, mp) for mp in MARKETPLACES}
    scores = _calcular_scores(metricas)
    vencedor = max(scores, key=scores.get) if scores else "mercadolivre"
    if scores.get("mercadolivre", 0) == scores.get("shopee", 0):
        vencedor = "empate"

    return {
        "ok": True,
        "id": segmento.get("id"),
        "nome": segmento.get("nome") or segmento.get("id"),
        "categoria": str(segmento.get("categoria") or "").lower(),
        "termo_busca": segmento.get("termo_busca"),
        "prioridade": int(segmento.get("prioridade") or 99),
        "total_anuncios": len(anuncios),
        "por_marketplace": metricas,
        "scores": scores,
        "vencedor": vencedor,
    }


def consolidar_categoria(resultados_termos: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrega vários termos da mesma categoria."""
    ok = [r for r in resultados_termos if r.get("ok")]
    if not ok:
        return {"ok": False, "motivo": "sem termos", "resultados": resultados_termos}

    categoria = str(ok[0].get("categoria") or "")
    agg: dict[str, dict[str, float]] = {
        mp: {
            "anuncios": 0.0,
            "vendidos": 0.0,
            "volume_sinal": 0.0,
            "cobertura_sum": 0.0,
            "preco_sum": 0.0,
            "preco_n": 0.0,
            "score_sum": 0.0,
            "proxy_n": 0.0,
        }
        for mp in MARKETPLACES
    }

    for r in ok:
        scores = r.get("scores") or {}
        por = r.get("por_marketplace") or {}
        for mp in MARKETPLACES:
            m = por.get(mp) or {}
            a = agg[mp]
            a["anuncios"] += float(m.get("anuncios") or 0)
            a["vendidos"] += float(m.get("vendidos") or 0)
            a["volume_sinal"] += float(m.get("volume_sinal") or 0)
            a["cobertura_sum"] += float(m.get("cobertura_preco") or 0)
            if float(m.get("preco_mediana") or 0) > 0:
                a["preco_sum"] += float(m["preco_mediana"])
                a["preco_n"] += 1
            a["score_sum"] += float(scores.get(mp) or 0)
            if m.get("volume_eh_proxy"):
                a["proxy_n"] += 1

    n = max(1, len(ok))
    por_mp: dict[str, Any] = {}
    scores_cat: dict[str, float] = {}
    for mp in MARKETPLACES:
        a = agg[mp]
        score = round(a["score_sum"] / n, 4)
        scores_cat[mp] = score
        por_mp[mp] = {
            "marketplace": mp,
            "label": label_marketplace(mp),
            "anuncios": int(a["anuncios"]),
            "vendidos": int(a["vendidos"]),
            "volume_sinal": round(a["volume_sinal"], 2),
            "cobertura_preco": round(a["cobertura_sum"] / n, 4),
            "preco_mediana": round(a["preco_sum"] / a["preco_n"], 2) if a["preco_n"] else 0.0,
            "score": score,
            "volume_eh_proxy": a["proxy_n"] > 0,
        }

    vencedor = max(scores_cat, key=scores_cat.get)
    if scores_cat.get("mercadolivre", 0) == scores_cat.get("shopee", 0):
        vencedor = "empate"

    return {
        "ok": True,
        "categoria": categoria,
        "termos": len(ok),
        "por_marketplace": por_mp,
        "scores": scores_cat,
        "vencedor": vencedor,
        "resultados": ok,
    }


def consolidar_geral(categorias: list[dict[str, Any]]) -> dict[str, Any]:
    """Consolida categorias e escolhe vencedor global."""
    ok = [c for c in categorias if c.get("ok")]
    if not ok:
        return {
            "ok": False,
            "motivo": "sem categorias",
            "vencedor_global": None,
            "categorias": categorias,
            "razoes": [],
        }

    score_sum = {mp: 0.0 for mp in MARKETPLACES}
    vitorias = {mp: 0 for mp in MARKETPLACES}
    empates = 0
    razoes: list[str] = []

    for cat in ok:
        scores = cat.get("scores") or {}
        for mp in MARKETPLACES:
            score_sum[mp] += float(scores.get(mp) or 0)
        v = cat.get("vencedor")
        nome = cat.get("categoria") or "?"
        if v == "empate":
            empates += 1
            razoes.append(f"{nome}: empate técnico entre ML e Shopee")
        elif v in vitorias:
            vitorias[v] += 1
            por = cat.get("por_marketplace") or {}
            vencedor_m = por.get(v) or {}
            outro = "shopee" if v == "mercadolivre" else "mercadolivre"
            outro_m = por.get(outro) or {}
            razoes.append(
                f"{nome}: {label_marketplace(v)} (score {vencedor_m.get('score', 0):.2f} "
                f"vs {outro_m.get('score', 0):.2f}; "
                f"{vencedor_m.get('anuncios', 0)} anúncios)"
            )

    n = max(1, len(ok))
    scores_globais = {mp: round(score_sum[mp] / n, 4) for mp in MARKETPLACES}
    vencedor = max(scores_globais, key=scores_globais.get)
    if scores_globais.get("mercadolivre", 0) == scores_globais.get("shopee", 0):
        vencedor = "empate"

    return {
        "ok": True,
        "vencedor_global": vencedor,
        "scores_globais": scores_globais,
        "vitorias_categoria": vitorias,
        "empates_categoria": empates,
        "categorias": ok,
        "razoes": razoes,
        "nota_metodologica": (
            "Shopee competitiva não expõe quantidade vendida neste robô "
            "(busca Brave/DDG). Volume Shopee usa proxy anúncios×cobertura de preço."
        ),
    }


def gerar_recomendacoes(consolidado: dict[str, Any]) -> list[str]:
    """Sugestões acionáveis a partir do consolidado."""
    recs: list[str] = []
    if not consolidado.get("ok"):
        return ["Sem dados suficientes para recomendar canal."]

    vencedor = consolidado.get("vencedor_global")
    if vencedor == "empate":
        recs.append("Empate global: teste A/B com o mesmo SKU nos dois marketplaces e compare ROI de ads.")
    elif vencedor:
        recs.append(
            f"Priorize estoque e ads no {label_marketplace(vencedor)} "
            f"(melhor score médio nas categorias varridas)."
        )
        outro = "shopee" if vencedor == "mercadolivre" else "mercadolivre"
        recs.append(
            f"Mantenha presença leve no {label_marketplace(outro)} para captura de busca, "
            "sem forçar orçamento de anúncio até haver giro próprio."
        )

    for cat in consolidado.get("categorias") or []:
        nome = cat.get("categoria") or "?"
        v = cat.get("vencedor")
        por = cat.get("por_marketplace") or {}
        ml = por.get("mercadolivre") or {}
        sh = por.get("shopee") or {}
        if v == "mercadolivre" and int(ml.get("vendidos") or 0) > 0:
            recs.append(
                f"{nome}: ML tem prova de giro ({ml.get('vendidos')} un. nos anúncios amostrados) — "
                "fortaleça listing e Product Ads aí."
            )
        if v == "shopee" and sh.get("volume_eh_proxy"):
            recs.append(
                f"{nome}: Shopee lidera por densidade/preço (proxy, sem vendas públicas) — "
                "valide com pedidos da sua loja antes de escalar."
            )
        if int(sh.get("anuncios") or 0) > int(ml.get("anuncios") or 0) and v != "shopee":
            recs.append(
                f"{nome}: Shopee tem mais anúncios ({sh.get('anuncios')}) mas score inferior — "
                "mercado saturado sem evidência de giro."
            )

    # dedupe preservando ordem
    vistos: set[str] = set()
    unicos: list[str] = []
    for r in recs:
        if r not in vistos:
            vistos.add(r)
            unicos.append(r)
    return unicos[:8]


def _texto_pedido(pedido: dict[str, Any]) -> str:
    partes = [str(pedido.get("titulo") or "")]
    for it in pedido.get("itens") or []:
        if not isinstance(it, dict):
            continue
        partes.append(str(it.get("sku") or ""))
        partes.append(str(it.get("titulo") or ""))
        partes.append(str(it.get("item_id") or ""))
    return " ".join(partes).lower()


def filtrar_pedidos_por_categoria(
    pedidos: list[dict[str, Any]],
    categoria: str,
) -> list[dict[str, Any]]:
    tokens = tokens_categoria(categoria)
    if not tokens:
        return list(pedidos)
    out: list[dict[str, Any]] = []
    for p in pedidos:
        blob = _texto_pedido(p)
        if any(tok in blob for tok in tokens):
            out.append(p)
    return out


def resumir_pedidos_proprios(
    *,
    pedidos_ml: list[dict[str, Any]],
    pedidos_shopee: list[dict[str, Any]],
    categorias: list[str],
) -> dict[str, Any]:
    """Resume pedidos próprios 7d filtrados por tokens de categoria."""
    por_cat: dict[str, Any] = {}
    total_ml = 0
    total_sh = 0
    receita_ml = 0.0
    receita_sh = 0.0

    for cat in categorias:
        ml_f = filtrar_pedidos_por_categoria(pedidos_ml, cat)
        sh_f = filtrar_pedidos_por_categoria(pedidos_shopee, cat)
        r_ml = sum(float(p.get("total") or 0) for p in ml_f)
        r_sh = sum(float(p.get("total") or 0) for p in sh_f)
        total_ml += len(ml_f)
        total_sh += len(sh_f)
        receita_ml += r_ml
        receita_sh += r_sh
        por_cat[cat] = {
            "mercadolivre": {"pedidos": len(ml_f), "receita": round(r_ml, 2)},
            "shopee": {"pedidos": len(sh_f), "receita": round(r_sh, 2)},
            "vencedor": (
                "empate"
                if len(ml_f) == len(sh_f)
                else ("mercadolivre" if len(ml_f) > len(sh_f) else "shopee")
            ),
        }

    return {
        "ok": True,
        "dias": 7,
        "mercadolivre": {"pedidos": total_ml, "receita": round(receita_ml, 2)},
        "shopee": {"pedidos": total_sh, "receita": round(receita_sh, 2)},
        "por_categoria": por_cat,
        "tem_dados": total_ml > 0 or total_sh > 0,
    }
