"""
core/cenario_macro.py
Funções puras do cenário macro. Sem rede e sem leitura de arquivo.
Os defaults vêm de core.config; o chamador pode passar tudo por parâmetro.
"""
from __future__ import annotations

from typing import Any

from core.config import (
    CENARIO_CAMBIO_CHOQUE_PCT,
    CENARIO_CAMBIO_ESTRESSE_PCT,
    CENARIO_COBERTURA_ALVO_DIAS,
    CENARIO_CUSTO_CAPITAL_MES_PCT,
)
from core.precificacao_comportamento import calcular_lucro_operacao, calcular_preco_piso

_TETO_MARGEM_PCT = 60.0


def regime_cambial(
    usd_brl: float,
    referencia: float,
    *,
    estresse_pct: float | None = None,
    choque_pct: float | None = None,
) -> dict[str, float | str]:
    """Classifica o dólar contra uma referência manual. Sem número macro embutido."""
    estresse = CENARIO_CAMBIO_ESTRESSE_PCT if estresse_pct is None else float(estresse_pct)
    choque = CENARIO_CAMBIO_CHOQUE_PCT if choque_pct is None else float(choque_pct)
    try:
        usd = float(usd_brl)
        ref = float(referencia)
    except (TypeError, ValueError):
        return {"regime": "sem_referencia", "variacao_pct": 0.0}
    if ref <= 0 or usd <= 0:
        return {"regime": "sem_referencia", "variacao_pct": 0.0}
    variacao = (usd / ref - 1.0) * 100.0
    if variacao >= choque:
        regime = "choque"
    elif variacao >= estresse:
        regime = "estresse"
    else:
        regime = "calmo"
    return {"regime": regime, "variacao_pct": round(variacao, 4)}


def margem_exigida_pct(
    fase: int,
    base_por_fase: dict[int, float],
    adicional_pp: float,
    ativo: bool,
) -> float:
    """Margem da fase. Com cenário ativo soma pontos; nunca reduz; teto de 60."""
    try:
        fase_i = int(fase)
    except (TypeError, ValueError):
        fase_i = 1
    base = float(base_por_fase.get(fase_i, base_por_fase.get(1, 0.0)))
    if not ativo:
        return base
    try:
        extra = float(adicional_pp)
    except (TypeError, ValueError):
        extra = 0.0
    if extra < 0:
        extra = 0.0
    return min(_TETO_MARGEM_PCT, base + extra)


def custo_reposicao(custo_atual: float, alta_pct: float) -> float:
    """Custo depois do reajuste manual do fornecedor. Alta negativa é ignorada."""
    try:
        custo = float(custo_atual)
        alta = float(alta_pct)
    except (TypeError, ValueError):
        return 0.0
    if alta < 0:
        alta = 0.0
    return round(custo * (1.0 + alta / 100.0), 2)


def custo_carregamento_estoque(custo_unit: float, dias: int, custo_mes_pct: float) -> float:
    """Custo do capital parado em uma unidade durante `dias` (mês = 30 dias)."""
    try:
        custo = float(custo_unit)
        dias_i = int(dias)
        taxa = float(custo_mes_pct)
    except (TypeError, ValueError):
        return 0.0
    if custo <= 0 or dias_i <= 0 or taxa <= 0:
        return 0.0
    return round(custo * (taxa / 100.0) * (dias_i / 30.0), 2)


def preco_equilibrio(custo_total: float, taxa_canal_pct: float, margem_pct: float) -> float:
    """Piso de preço. Reusa calcular_preco_piso — não duplica a fórmula."""
    return round(calcular_preco_piso(custo_total, taxa_canal_pct, margem_pct), 2)


def _margem_sobre_preco(preco: float, custo: float, taxa_canal_pct: float) -> float:
    if preco <= 0:
        return 0.0
    lucro = calcular_lucro_operacao(preco, custo, taxa_canal_pct)
    return float(lucro["margem_operacional_pct"])


def recomendar_sku(
    *,
    sku: str,
    custo_total: float,
    custo_reposicao_unit: float,
    preco_atual: float,
    taxa_canal_pct: float,
    fase: int,
    estoque: int,
    vendas_dia: float | None,
    margem_exigida: float,
    cobertura_alvo_dias: int | None = None,
    custo_capital_mes_pct: float | None = None,
) -> dict[str, Any]:
    """Sugere uma ação de margem/estoque. Não escreve preço em lugar nenhum."""
    alvo = CENARIO_COBERTURA_ALVO_DIAS if cobertura_alvo_dias is None else int(cobertura_alvo_dias)
    taxa_capital = (
        CENARIO_CUSTO_CAPITAL_MES_PCT if custo_capital_mes_pct is None else float(custo_capital_mes_pct)
    )
    try:
        custo = float(custo_total)
        reposicao = float(custo_reposicao_unit)
        preco = float(preco_atual)
        taxa = float(taxa_canal_pct)
        exigida = float(margem_exigida)
        estoque_i = int(estoque or 0)
    except (TypeError, ValueError):
        return {
            "sku": sku,
            "acao": "revisar_dados",
            "motivo": "Custo, preço ou estoque inválido.",
            "margem_atual_pct": None,
            "margem_na_reposicao_pct": None,
            "preco_equilibrio_reposicao": 0.0,
            "cobertura_dias": None,
        }

    vendas = None
    if vendas_dia is not None:
        try:
            vendas_f = float(vendas_dia)
            vendas = vendas_f if vendas_f > 0 else None
        except (TypeError, ValueError):
            vendas = None
    cobertura = round(estoque_i / vendas, 1) if vendas else None

    margem_atual = _margem_sobre_preco(preco, custo, taxa) if preco > 0 else None
    margem_rep = _margem_sobre_preco(preco, reposicao, taxa) if preco > 0 else None
    piso = preco_equilibrio(reposicao if reposicao > 0 else custo, taxa, exigida)

    base = {
        "sku": sku,
        "fase": fase,
        "margem_atual_pct": margem_atual,
        "margem_na_reposicao_pct": margem_rep,
        "preco_equilibrio_reposicao": piso,
        "cobertura_dias": cobertura,
        "margem_exigida_pct": exigida,
    }

    if custo <= 0 or preco <= 0:
        return {**base, "acao": "revisar_dados", "motivo": "Custo ou preço atual menor ou igual a zero."}

    if margem_rep is not None and margem_rep < exigida:
        return {
            **base,
            "acao": "subir_preco_na_reposicao",
            "motivo": (
                f"Na reposição a margem fica {margem_rep:.1f}%, abaixo dos {exigida:.1f}% exigidos. "
                f"Piso de equilíbrio R$ {piso:.2f}."
            ),
        }

    if reposicao > custo and cobertura is not None and cobertura < alvo:
        ganho = round(reposicao - custo, 2)
        dias_parado = max(1, alvo)
        carregamento = custo_carregamento_estoque(custo, dias_parado, taxa_capital)
        if carregamento < ganho:
            return {
                **base,
                "acao": "antecipar_compra",
                "motivo": (
                    f"Reposição sobe R$ {ganho:.2f}/un e a cobertura ({cobertura:.0f}d) "
                    f"está abaixo de {alvo}d. Carregamento R$ {carregamento:.2f} < ganho."
                ),
                "ganho_antecipar_brl": ganho,
                "carregamento_brl": carregamento,
            }

    sem_giro = vendas is None and estoque_i > 0
    if (cobertura is not None and cobertura > 2 * alvo) or sem_giro:
        return {
            **base,
            "acao": "nao_repor_sem_giro",
            "motivo": (
                "Sem giro com estoque parado."
                if sem_giro
                else f"Cobertura {cobertura:.0f}d passa de {2 * alvo}d (2× o alvo)."
            ),
        }

    return {
        **base,
        "acao": "manter",
        "motivo": "Margem na reposição cobre o exigido e a cobertura está na faixa.",
    }
