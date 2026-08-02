"""core/claude_ml/stress.py — termômetro do produto/nicho (SRP)."""
from __future__ import annotations

from typing import Any

from core.claude_ml.numeros import num, primeiro_num


def stress_produto(
    consolidado: dict[str, Any] | None = None,
    *,
    produto: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score 0–100 + nível baixo|medio|alto."""
    score = 0
    fatores: list[str] = []
    c = consolidado if isinstance(consolidado, dict) else {}
    p = produto if isinstance(produto, dict) else {}

    margem = p.get("margem_pct")
    if margem is None:
        margem = c.get("margem_media_pct")
    if (
        margem is None
        and c.get("margem_media_brl") is not None
        and c.get("margem_media_pct") is None
    ):
        if num(c.get("margem_media_brl")) < 8:
            score += 25
            fatores.append("margem_brl_baixa:+25")
    elif margem is not None:
        m = num(margem)
        if m < 12:
            score += 35
            fatores.append("margem_pct_critica:+35")
        elif m < 20:
            score += 18
            fatores.append("margem_pct_apertada:+18")

    ganhos = c.get("maior_ganho") or []
    if isinstance(ganhos, list) and ganhos:
        d0 = ganhos[0] if isinstance(ganhos[0], dict) else {}
        delta = num(d0.get("delta_vendas"))
        if delta < 0:
            score += 20
            fatores.append("delta_vendas_negativo:+20")
        elif delta == 0 and d0.get("ganho_fonte") == "sem_historico_usa_vendas":
            score += 8
            fatores.append("sem_historico_delta:+8")

    anuncios = primeiro_num(c.get("total_anuncios_ativos"), c.get("total_produtos_unicos"))
    vendas = primeiro_num(
        c.get("vendas_totais"),
        c.get("total_vendas"),
        p.get("quantidade_vendida"),
    )
    if anuncios > 0 and vendas == 0:
        score += 40
        fatores.append("anuncios_sem_venda:+40")
    elif anuncios >= 10 and vendas < anuncios:
        score += 12
        fatores.append("vendas_baixas_vs_catalogo:+12")

    preco = primeiro_num(p.get("preco"), c.get("preco_medio"))
    custo = primeiro_num(p.get("custo_unitario_brl"), p.get("custo"))
    if preco > 0 and custo > 0 and preco <= custo * 1.15:
        score += 25
        fatores.append("preco_perto_custo:+25")

    score = max(0, min(100, int(score)))
    if score >= 40:
        nivel = "alto"
    elif score >= 20:
        nivel = "medio"
    else:
        nivel = "baixo"

    return {"score": score, "nivel": nivel, "fatores": fatores}
