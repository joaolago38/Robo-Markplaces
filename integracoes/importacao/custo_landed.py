"""
integracoes/importacao/custo_landed.py
Custo landed (CIF + tributos/despesas aduaneiras BR + frete nacional)
China → Brasil — referência legislação brasileira (estimativa de planejamento).

Cascata (regime comum de importação formal):
  valor aduaneiro (CIF ≈ FOB+frete+seguro) → II → IPI → PIS/COFINS-Importação
  → despesas aduaneiras (Siscomex, desembaraço, AFRMM no marítimo) → ICMS “por dentro”.

Referências (não substituem despachante):
  - Valor aduaneiro / RA (Decreto 6.759/2009)
  - II (TEC) · IPI (TIPI)
  - PIS/COFINS-Importação (Lei 10.865/2004) — alíquotas padrão 2,1% + 9,65%
  - Taxa de utilização do Siscomex
  - AFRMM (Lei 10.893/2004 art. 6º, redação Lei 14.301/2022 — 8% longo curso)
  - ICMS importação (base e cálculo “por dentro” — legislação estadual / Convênios ICMS)
"""
from __future__ import annotations

from typing import Any, Literal

ModoFrete = Literal["maritimo", "aereo"]

# Referência documental embutida nos resultados
REFERENCIA_LEGISLACAO_BR = {
    "valor_aduaneiro": "Decreto 6.759/2009 (RA) — CIF estimado FOB+frete+seguro",
    "ii": "Imposto de Importação — TEC (alíquota por NCM)",
    "ipi": "IPI — TIPI (base CIF+II)",
    "pis_cofins": "Lei 10.865/2004 — PIS/COFINS-Importação sobre valor aduaneiro",
    "siscomex": "Taxa Siscomex — Portaria ME 4.131/2021 + IN RFB 2.024/2021 (DI + adições)",
    "afrmm": "Lei 10.893/2004 art. 6º (Lei 14.301/2022) — AFRMM 8% frete longo curso",
    "icms": "ICMS importação — alíquota UF destino, cálculo por dentro",
    "aviso": "Estimativa de planejamento; confirme NCM/alíquotas e benefícios com despachante.",
}


def calcular_custo_landed(
    preco_usd_unit: float,
    *,
    cambio_usd_brl: float,
    peso_kg_unit: float = 1.0,
    quantidade: int = 1,
    modo_frete: ModoFrete = "maritimo",
    ii_pct: float = 16.0,
    ipi_pct: float = 0.0,
    pis_pct: float = 2.1,
    cofins_pct: float = 9.65,
    icms_pct: float = 18.0,
    frete_maritimo_usd_kg: float = 0.85,
    frete_aereo_usd_kg: float = 5.5,
    seguro_pct: float = 0.5,
    siscomex_brl: float | None = None,
    desembaraco_brl: float = 800.0,
    frete_nacional_brl_unit: float = 12.0,
    afrmm_pct: float | None = None,
    siscomex_adicoes: int = 1,
) -> dict[str, Any]:
    """
    Estima custo unitário landed com frete marítimo ou aéreo e tributos/despesas
    aduaneiras brasileiras. Frete nacional (pós-desembaraço) fora da base do ICMS.
    """
    try:
        preco_usd = float(preco_usd_unit)
        cambio = float(cambio_usd_brl)
        peso = max(0.01, float(peso_kg_unit))
        qty = max(1, int(quantidade))
    except (TypeError, ValueError):
        return {"ok": False, "motivo": "parâmetros numéricos inválidos"}

    if preco_usd <= 0 or cambio <= 0:
        return {"ok": False, "motivo": "preço ou câmbio inválido"}

    from integracoes.importacao.siscomex import calcular_taxa_siscomex

    # Siscomex: se None ou legado 214.50 → calcula pela regra vigente
    if siscomex_brl is None or abs(float(siscomex_brl) - 214.50) < 0.01:
        siscomex_detalhe = calcular_taxa_siscomex(adicoes=max(1, int(siscomex_adicoes or 1)))
        siscomex_brl = float(siscomex_detalhe["total_brl"])
    else:
        siscomex_brl = float(siscomex_brl)
        siscomex_detalhe = calcular_taxa_siscomex(adicoes=max(1, int(siscomex_adicoes or 1)))
        siscomex_detalhe = {**siscomex_detalhe, "total_brl": round(siscomex_brl, 2), "origem": "override"}

    # AFRMM: 8% longo curso (Lei 10.893/2004 art. 6º c/ redação Lei 14.301/2022).
    # Override via afrmm_pct; se None, usa IMPORTACAO_AFRMM_PCT (marítimo) ou 0 (aéreo).
    if afrmm_pct is None:
        if modo_frete == "maritimo":
            try:
                from core.config import IMPORTACAO_AFRMM_PCT

                afrmm_pct = float(IMPORTACAO_AFRMM_PCT)
            except Exception:
                afrmm_pct = 8.0
        else:
            afrmm_pct = 0.0
    else:
        afrmm_pct = float(afrmm_pct)

    fob_usd_total = preco_usd * qty
    fob_brl_total = fob_usd_total * cambio

    peso_total_kg = peso * qty
    frete_usd_kg = frete_maritimo_usd_kg if modo_frete == "maritimo" else frete_aereo_usd_kg
    frete_usd_total = peso_total_kg * frete_usd_kg
    frete_brl_total = frete_usd_total * cambio

    seguro_brl = (fob_brl_total + frete_brl_total) * (seguro_pct / 100.0)
    cif_brl = fob_brl_total + frete_brl_total + seguro_brl

    ii_brl = cif_brl * (ii_pct / 100.0)
    ipi_brl = (cif_brl + ii_brl) * (ipi_pct / 100.0)
    pis_brl = cif_brl * (pis_pct / 100.0)
    cofins_brl = cif_brl * (cofins_pct / 100.0)

    # AFRMM sobre frete internacional (marítimo); entra como despesa aduaneira na base ICMS
    afrmm_brl = frete_brl_total * (afrmm_pct / 100.0) if afrmm_pct > 0 else 0.0

    despesas_aduaneiras_brl = siscomex_brl + desembaraco_brl + afrmm_brl
    base_sem_icms = cif_brl + ii_brl + ipi_brl + pis_brl + cofins_brl + despesas_aduaneiras_brl
    aliq_icms = icms_pct / 100.0
    icms_brl = base_sem_icms / (1.0 - aliq_icms) * aliq_icms if 0 < aliq_icms < 1 else 0.0

    frete_nacional_total = frete_nacional_brl_unit * qty
    custo_total_brl = base_sem_icms + icms_brl + frete_nacional_total
    custo_unitario_brl = round(custo_total_brl / qty, 2)

    impostos_federais = ii_brl + ipi_brl + pis_brl + cofins_brl
    return {
        "ok": True,
        "modo_frete": modo_frete,
        "quantidade": qty,
        "peso_kg_unit": peso,
        "peso_total_kg": round(peso_total_kg, 3),
        "cambio_usd_brl": round(cambio, 4),
        "fob_usd_unit": round(preco_usd, 4),
        "fob_brl_total": round(fob_brl_total, 2),
        "frete_internacional_usd": round(frete_usd_total, 2),
        "frete_internacional_brl": round(frete_brl_total, 2),
        "seguro_brl": round(seguro_brl, 2),
        "cif_brl": round(cif_brl, 2),
        "valor_aduaneiro_cif_brl": round(cif_brl, 2),
        "ii_pct": ii_pct,
        "ii_brl": round(ii_brl, 2),
        "ipi_pct": ipi_pct,
        "ipi_brl": round(ipi_brl, 2),
        "pis_pct": pis_pct,
        "pis_brl": round(pis_brl, 2),
        "cofins_pct": cofins_pct,
        "cofins_brl": round(cofins_brl, 2),
        "pis_cofins_brl": round(pis_brl + cofins_brl, 2),
        "icms_pct": icms_pct,
        "icms_brl": round(icms_brl, 2),
        "siscomex_brl": round(siscomex_brl, 2),
        "siscomex_adicoes": max(1, int(siscomex_adicoes or 1)),
        "siscomex_detalhe": siscomex_detalhe,
        "desembaraco_brl": round(desembaraco_brl, 2),
        "afrmm_pct": afrmm_pct,
        "afrmm_brl": round(afrmm_brl, 2),
        "despesas_aduaneiras_brl": round(despesas_aduaneiras_brl, 2),
        "frete_nacional_brl": round(frete_nacional_total, 2),
        "impostos_federais_brl": round(impostos_federais, 2),
        "impostos_total_brl": round(impostos_federais + icms_brl, 2),
        "custo_total_brl": round(custo_total_brl, 2),
        "custo_unitario_brl": custo_unitario_brl,
        "referencia_legislacao_br": REFERENCIA_LEGISLACAO_BR,
        "despesas_aduaneiras_inclusas": True,
    }


def calcular_cenarios_frete(
    preco_usd_unit: float,
    *,
    cambio_usd_brl: float,
    peso_kg_unit: float = 1.0,
    quantidade: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    """Retorna custo landed marítimo e aéreo lado a lado."""
    kwargs_mar = dict(kwargs)
    kwargs_aer = dict(kwargs)
    # AFRMM (Lei 10.893/2004) só no marítimo
    kwargs_aer["afrmm_pct"] = 0.0

    maritimo = calcular_custo_landed(
        preco_usd_unit,
        cambio_usd_brl=cambio_usd_brl,
        peso_kg_unit=peso_kg_unit,
        quantidade=quantidade,
        modo_frete="maritimo",
        **kwargs_mar,
    )
    aereo = calcular_custo_landed(
        preco_usd_unit,
        cambio_usd_brl=cambio_usd_brl,
        peso_kg_unit=peso_kg_unit,
        quantidade=quantidade,
        modo_frete="aereo",
        **kwargs_aer,
    )
    melhor = None
    if maritimo.get("ok") and aereo.get("ok"):
        melhor = (
            "maritimo"
            if maritimo["custo_unitario_brl"] <= aereo["custo_unitario_brl"]
            else "aereo"
        )
    return {"maritimo": maritimo, "aereo": aereo, "melhor_frete": melhor}


def calcular_margem_revenda(
    preco_venda_brl: float,
    custo_unitario_brl: float,
    *,
    taxa_marketplace_pct: float = 14.0,
    margem_minima_pct: float = 18.0,
    margem_minima_reais: float = 5.0,
) -> dict[str, Any]:
    try:
        venda = float(preco_venda_brl)
        custo = float(custo_unitario_brl)
    except (TypeError, ValueError):
        return {"ok": False}
    if venda <= 0 or custo < 0:
        return {"ok": False}

    liquido = venda * (1.0 - taxa_marketplace_pct / 100.0)
    margem_brl = round(liquido - custo, 2)
    margem_pct = round(margem_brl / venda * 100.0, 1) if venda > 0 else 0.0
    lucro_razoavel = margem_pct >= margem_minima_pct and margem_brl >= margem_minima_reais

    return {
        "ok": True,
        "preco_venda_brl": round(venda, 2),
        "custo_unitario_brl": round(custo, 2),
        "liquido_apos_taxa_brl": round(liquido, 2),
        "taxa_marketplace_pct": taxa_marketplace_pct,
        "margem_brl": margem_brl,
        "margem_pct": margem_pct,
        "lucro_razoavel": lucro_razoavel,
    }
