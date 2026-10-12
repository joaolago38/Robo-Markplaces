"""
core/precificacao_comportamento.py
Sugere preços com base em comportamento de compra + concorrência + margem.
"""
from __future__ import annotations

from typing import Any


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def calcular_preco_piso(custo: float, taxa_canal_pct: float, margem_minima_pct: float) -> float:
    taxa = max(0.0, min(99.0, taxa_canal_pct)) / 100.0
    margem = max(0.0, min(99.0, margem_minima_pct)) / 100.0
    denominador = 1 - taxa - margem
    if custo <= 0 or denominador <= 0:
        return 0.0
    return custo / denominador


def calcular_lucro_operacao(preco: float, custo: float, taxa_canal_pct: float) -> dict[str, float]:
    """
    Lucro líquido da operação: receita após taxa do marketplace menos custo do produto.
    """
    preco = _f(preco)
    custo = _f(custo)
    taxa = max(0.0, min(99.0, taxa_canal_pct)) / 100.0
    receita_liquida = preco * (1 - taxa)
    lucro = receita_liquida - custo
    margem_pct = (lucro / preco * 100) if preco > 0 else 0.0
    return {
        "receita_liquida": round(receita_liquida, 2),
        "lucro_reais": round(lucro, 2),
        "margem_operacional_pct": round(margem_pct, 2),
    }


def calcular_preco_ideal(
    *,
    preco_atual: float,
    custo: float,
    preco_concorrente: float | None,
    margem_minima_pct: float,
    taxa_canal_pct: float,
    abaixo_concorrente_pct: float,
    sinais: dict[str, Any] | None = None,
    preco_fase: float | None = None,
) -> dict[str, Any]:
    """
    Retorna preço sugerido, motivo e diagnóstico de comportamento do comprador.
    """
    from core.config import (
        PRECIFICACAO_DEMANDA_FORTE_AUMENTO_PCT,
        PRECIFICACAO_VISITAS_SEM_VENDA_DESCONTO_PCT,
    )

    sinais = sinais or {}
    preco_atual = _f(preco_atual)
    custo = _f(custo)
    preco_piso = calcular_preco_piso(custo, taxa_canal_pct, margem_minima_pct)

    candidatos: list[tuple[float, str]] = []
    if preco_piso > 0:
        candidatos.append((preco_piso, "piso de margem"))

    if preco_fase and preco_fase > 0:
        candidatos.append((_f(preco_fase), "preço da fase no catálogo"))

    conc = _f(preco_concorrente) if preco_concorrente else 0.0
    if conc > 0:
        alvo_conc = conc * (1 - abaixo_concorrente_pct / 100.0)
        candidatos.append((alvo_conc, f"concorrência −{abaixo_concorrente_pct:.0f}%"))

    sugerido_ml = _f(sinais.get("preco_sugerido_ml"))
    if sugerido_ml > 0:
        candidatos.append((sugerido_ml, "sugestão Mercado Livre"))

    visitas_7d = int(sinais.get("visitas_7d") or 0)
    visitas_30d = int(sinais.get("visitas_30d") or 0)
    unidades_7d = int(sinais.get("unidades_vendidas_7d") or 0)
    vendas_dia = _f(sinais.get("vendas_por_dia"))
    qtd_lider = int(sinais.get("quantidade_vendida_lider") or 0)

    comportamento = "estável"
    ajuste_comportamento = 0.0

    media_diaria_30d = visitas_30d / 30.0 if visitas_30d > 0 else 0.0
    media_diaria_7d = visitas_7d / 7.0 if visitas_7d > 0 else 0.0

    if visitas_7d >= 15 and unidades_7d == 0 and preco_atual > 0:
        ajuste_comportamento = -preco_atual * (PRECIFICACAO_VISITAS_SEM_VENDA_DESCONTO_PCT / 100.0)
        comportamento = "muito interesse, zero vendas — testar preço mais atrativo"
    elif unidades_7d >= 2 and preco_atual > 0:
        margem_atual = ((preco_atual - custo) / preco_atual * 100) if preco_atual > 0 else 0
        if margem_atual > margem_minima_pct + 8:
            ajuste_comportamento = preco_atual * (PRECIFICACAO_DEMANDA_FORTE_AUMENTO_PCT / 100.0)
            comportamento = "demanda forte — espaço para subir preço"
    elif media_diaria_7d > 0 and media_diaria_30d > 0 and media_diaria_7d < media_diaria_30d * 0.5:
        comportamento = "tráfego caindo — revisar título/fotos antes de mexer no preço"
    elif conc > 0 and qtd_lider > max(unidades_7d * 3, 5) and preco_atual >= conc * 0.98:
        alvo_match = conc * (1 - max(1.0, abaixo_concorrente_pct - 1) / 100.0)
        candidatos.append((alvo_match, "líder vende mais com preço similar"))

    candidatos_competicao = [c for c in candidatos if c[1] != "piso de margem"]
    if candidatos_competicao:
        base = max(c[0] for c in candidatos_competicao)
    elif preco_atual > 0:
        base = preco_atual
    else:
        base = max((c[0] for c in candidatos), default=custo)

    preco_sugerido = round(max(preco_piso, custo, base + ajuste_comportamento), 2)
    margem_pct = ((preco_sugerido - custo) / preco_sugerido * 100) if preco_sugerido > 0 else 0.0

    lucro_atual = calcular_lucro_operacao(preco_atual, custo, taxa_canal_pct)
    lucro_sugerido = calcular_lucro_operacao(preco_sugerido, custo, taxa_canal_pct)
    lucro_ok = lucro_sugerido["margem_operacional_pct"] >= margem_minima_pct - 0.05

    motivos = [c[1] for c in candidatos if abs(c[0] - preco_sugerido) < 0.05]
    if ajuste_comportamento != 0:
        motivos.append(comportamento)
    if not motivos:
        motivos.append("manter preço atual")

    acao = "manter"
    if not lucro_ok and preco_sugerido <= preco_piso + 0.02:
        acao = "manter — piso de lucro operacional"
    elif preco_sugerido < preco_atual - 0.49:
        acao = "reduzir para atrair vendas"
    elif preco_sugerido > preco_atual + 0.49:
        acao = "subir — demanda suporta"
    elif unidades_7d == 0 and visitas_7d >= 10:
        acao = "monitorar — tráfego sem conversão"

    return {
        "preco_atual": round(preco_atual, 2),
        "preco_sugerido": preco_sugerido,
        "preco_piso": round(preco_piso, 2),
        "preco_concorrente": round(conc, 2) if conc > 0 else None,
        "margem_pct": round(margem_pct, 2),
        "margem_minima_pct": round(margem_minima_pct, 2),
        "taxa_canal_pct": round(taxa_canal_pct, 2),
        "custo": round(custo, 2),
        "lucro_operacao": {
            "atual_reais": lucro_atual["lucro_reais"],
            "sugerido_reais": lucro_sugerido["lucro_reais"],
            "margem_atual_pct": lucro_atual["margem_operacional_pct"],
            "margem_sugerida_pct": lucro_sugerido["margem_operacional_pct"],
            "delta_lucro_reais": round(lucro_sugerido["lucro_reais"] - lucro_atual["lucro_reais"], 2),
            "lucro_ok": lucro_ok,
        },
        "comportamento": comportamento,
        "acao": acao,
        "motivos": motivos,
        "sinais": {
            "visitas_7d": visitas_7d,
            "visitas_30d": visitas_30d,
            "unidades_vendidas_7d": unidades_7d,
            "vendas_por_dia": round(vendas_dia, 2),
            "preco_sugerido_ml": sugerido_ml or None,
            "quantidade_vendida_lider": qtd_lider or None,
        },
    }
