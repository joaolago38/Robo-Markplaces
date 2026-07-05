"""
integracoes/importacao/custo_landed.py
Custo landed (CIF + impostos BR + frete nacional) para importação China → Brasil.
"""
from __future__ import annotations

from typing import Any, Literal

ModoFrete = Literal["maritimo", "aereo"]


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
    siscomex_brl: float = 214.50,
    desembaraco_brl: float = 800.0,
    frete_nacional_brl_unit: float = 12.0,
) -> dict[str, Any]:
    """
    Estima custo unitário landed com frete marítimo ou aéreo e tributos de importação.
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

    base_sem_icms = cif_brl + ii_brl + ipi_brl + pis_brl + cofins_brl + siscomex_brl + desembaraco_brl
    aliq_icms = icms_pct / 100.0
    icms_brl = base_sem_icms / (1.0 - aliq_icms) * aliq_icms if 0 < aliq_icms < 1 else 0.0

    frete_nacional_total = frete_nacional_brl_unit * qty
    custo_total_brl = base_sem_icms + icms_brl + frete_nacional_total
    custo_unitario_brl = round(custo_total_brl / qty, 2)

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
        "ii_pct": ii_pct,
        "ii_brl": round(ii_brl, 2),
        "ipi_pct": ipi_pct,
        "ipi_brl": round(ipi_brl, 2),
        "pis_brl": round(pis_brl, 2),
        "cofins_brl": round(cofins_brl, 2),
        "icms_pct": icms_pct,
        "icms_brl": round(icms_brl, 2),
        "siscomex_brl": round(siscomex_brl, 2),
        "desembaraco_brl": round(desembaraco_brl, 2),
        "frete_nacional_brl": round(frete_nacional_total, 2),
        "impostos_total_brl": round(ii_brl + ipi_brl + pis_brl + cofins_brl + icms_brl, 2),
        "custo_total_brl": round(custo_total_brl, 2),
        "custo_unitario_brl": custo_unitario_brl,
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
    maritimo = calcular_custo_landed(
        preco_usd_unit,
        cambio_usd_brl=cambio_usd_brl,
        peso_kg_unit=peso_kg_unit,
        quantidade=quantidade,
        modo_frete="maritimo",
        **kwargs,
    )
    aereo = calcular_custo_landed(
        preco_usd_unit,
        cambio_usd_brl=cambio_usd_brl,
        peso_kg_unit=peso_kg_unit,
        quantidade=quantidade,
        modo_frete="aereo",
        **kwargs,
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
