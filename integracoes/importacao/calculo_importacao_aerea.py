"""
integracoes/importacao/calculo_importacao_aerea.py
Cálculo formal de importação aérea CNPJ — Viracopos (VCP) → Americana-SP.
Função pura testável: calcular_custo_importacao_aerea_formal().
"""
from __future__ import annotations

import csv
import io
from typing import Any

from core.atomic_io import ler_json
from core.config import IMPORTACAO_OPERACAO_FIXA_CATALOGO, ROOT

# Alíquotas ICMS internas por UF (importação formal — referência)
_ICMS_UF_PCT: dict[str, float] = {
    "AC": 19.0,
    "AL": 19.0,
    "AP": 18.0,
    "AM": 18.0,
    "BA": 20.5,
    "CE": 18.0,
    "DF": 18.0,
    "ES": 17.0,
    "GO": 19.0,
    "MA": 18.0,
    "MT": 17.0,
    "MS": 17.0,
    "MG": 18.0,
    "PA": 17.0,
    "PB": 18.0,
    "PR": 18.0,
    "PE": 18.0,
    "PI": 18.0,
    "RJ": 20.0,
    "RN": 18.0,
    "RS": 17.0,
    "RO": 17.5,
    "RR": 17.0,
    "SC": 17.0,
    "SP": 18.0,
    "SE": 18.0,
    "TO": 18.0,
}


def icms_pct_por_uf(uf: str) -> float:
    return float(_ICMS_UF_PCT.get((uf or "SP").upper(), 18.0))


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _i(val: Any, default: int = 1) -> int:
    try:
        return max(1, int(val))
    except (TypeError, ValueError):
        return default


def _pct_sobre_total(valor: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return round(valor / total * 100.0, 2)


def carregar_defaults_operacao() -> dict[str, Any]:
    return ler_json(ROOT / IMPORTACAO_OPERACAO_FIXA_CATALOGO, default={})


def montar_entradas_de_produto(
    produto: dict[str, Any],
    oportunidade: dict[str, Any] | None = None,
    *,
    cambio_usd_brl: float,
    operacao: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mapeia produto Alibaba + oportunidade para entradas do cálculo formal."""
    op = operacao or carregar_defaults_operacao()
    dest = op.get("destino_entrega") or {}
    custos = op.get("custos_viracopos_brl") or {}
    oportunidade = oportunidade or {}

    preco_usd = oportunidade.get("preco_usd")
    if preco_usd is None:
        preco_usd = produto.get("preco_fob_usd")
    qty = _i(oportunidade.get("moq") or produto.get("moq_referencia") or 1)
    peso_unit = _f(produto.get("peso_kg"), 1.0)
    peso_cubado = produto.get("peso_cubado_kg")

    frete_usd_kg = _f(op.get("frete_aereo_usd_kg_estimativa"), 5.5)
    peso_taxavel = max(peso_unit, _f(peso_cubado, 0)) if peso_cubado else peso_unit
    frete_estimado_usd = peso_taxavel * qty * frete_usd_kg

    dist_km = _f(dest.get("distancia_km_viracopos"), 120.0)
    frete_rod = custos.get("frete_rodoviario_viracopos_destino")
    if frete_rod is None:
        frete_rod = dist_km * _f(custos.get("frete_rodoviario_por_km"), 5.5)

    uf = str(dest.get("uf") or "SP").upper()

    return {
        "fob_usd": _f(preco_usd),
        "peso_bruto_kg": peso_unit,
        "peso_cubado_kg": _f(peso_cubado) if peso_cubado else None,
        "frete_aereo_usd": _f(oportunidade.get("frete_aereo_usd"), frete_estimado_usd),
        "frete_aereo_usd_kg": frete_usd_kg,
        "estimar_frete_por_kg": oportunidade.get("frete_aereo_usd") is None,
        "seguro_pct": _f(produto.get("seguro_pct") or op.get("seguro_internacional_pct"), 0.5),
        "cambio_usd_brl": _f(cambio_usd_brl),
        "ncm": str(produto.get("ncm") or ""),
        "ii_pct": _f(produto.get("ii_pct"), 16.0),
        "ipi_pct": _f(produto.get("ipi_pct"), 0.0),
        "pis_cofins_pct": _f(produto.get("pis_cofins_pct") or op.get("pis_cofins_importacao_pct"), 11.75),
        "icms_pct": _f(produto.get("icms_pct") or op.get("icms_uf_padrao_pct"), icms_pct_por_uf(uf)),
        "uf_destino": uf,
        "quantidade": qty,
        "armazenagem_brl": _f(custos.get("armazenagem_aeroportuaria"), 450.0),
        "desembaraco_brl": _f(custos.get("desembaraco_despachante"), 1200.0),
        "thc_brl": _f(custos.get("thc_manuseio_aereo"), 380.0),
        "siscomex_brl": _f(custos.get("siscomex"), 214.5),
        "frete_rodoviario_brl": _f(frete_rod),
    }


def calcular_custo_importacao_aerea_formal(entradas: dict[str, Any]) -> dict[str, Any]:
    """
    Regime importação formal CNPJ — modal aéreo.
    Cascata: CIF → II → IPI → PIS/COFINS → base ICMS → ICMS por dentro.
    """
    fob_usd = _f(entradas.get("fob_usd"))
    cambio = _f(entradas.get("cambio_usd_brl"))
    qty = _i(entradas.get("quantidade"))
    peso_bruto = max(0.01, _f(entradas.get("peso_bruto_kg"), 1.0))
    peso_cubado = entradas.get("peso_cubado_kg")
    peso_taxavel_unit = max(peso_bruto, _f(peso_cubado, 0)) if peso_cubado else peso_bruto
    peso_taxavel_total = peso_taxavel_unit * qty

    if fob_usd <= 0 or cambio <= 0:
        return {"ok": False, "motivo": "FOB ou câmbio inválido"}

    frete_usd = _f(entradas.get("frete_aereo_usd"))
    if entradas.get("estimar_frete_por_kg") and frete_usd <= 0:
        frete_usd = peso_taxavel_total * _f(entradas.get("frete_aereo_usd_kg"), 5.5)

    seguro_pct = _f(entradas.get("seguro_pct"), 0.5)
    ii_pct = _f(entradas.get("ii_pct"), 16.0)
    ipi_pct = _f(entradas.get("ipi_pct"), 0.0)
    pis_cofins_pct = _f(entradas.get("pis_cofins_pct"), 11.75)
    icms_pct = _f(entradas.get("icms_pct"), 18.0)

    armazenagem = _f(entradas.get("armazenagem_brl"))
    desembaraco = _f(entradas.get("desembaraco_brl"))
    thc = _f(entradas.get("thc_brl"))
    siscomex = _f(entradas.get("siscomex_brl"))
    frete_rod = _f(entradas.get("frete_rodoviario_brl"))
    despesas_locais = armazenagem + desembaraco + thc + siscomex + frete_rod

    fob_brl = fob_usd * qty * cambio
    frete_brl = frete_usd * cambio
    seguro_brl = (fob_brl + frete_brl) * (seguro_pct / 100.0)
    cif_brl = fob_brl + frete_brl + seguro_brl

    ii_brl = cif_brl * (ii_pct / 100.0)
    ipi_brl = (cif_brl + ii_brl) * (ipi_pct / 100.0)
    pis_cofins_brl = cif_brl * (pis_cofins_pct / 100.0)

    base_icms = cif_brl + ii_brl + ipi_brl + pis_cofins_brl + despesas_locais
    aliq_icms = icms_pct / 100.0
    icms_brl = (aliq_icms * base_icms) / (1.0 - aliq_icms) if 0 < aliq_icms < 1 else 0.0

    custo_total_brl = base_icms + icms_brl
    custo_unitario_brl = round(custo_total_brl / qty, 2)

    impostos_federais = ii_brl + ipi_brl + pis_cofins_brl
    frete_seguro_brl = frete_brl + seguro_brl

    itens: list[dict[str, Any]] = []

    def _add(item_id: str, label: str, brl: float, grupo: str) -> None:
        itens.append(
            {
                "id": item_id,
                "label": label,
                "grupo": grupo,
                "brl": round(brl, 2),
                "pct_total": 0.0,
            }
        )

    _add("fob", "FOB mercadoria", fob_brl, "produto")
    _add("frete_int", "Frete aéreo internacional", frete_brl, "frete_seguro")
    _add("seguro", "Seguro internacional", seguro_brl, "frete_seguro")
    _add("ii", f"Imposto de Importação ({ii_pct}%)", ii_brl, "impostos_federais")
    _add("ipi", f"IPI ({ipi_pct}%)", ipi_brl, "impostos_federais")
    _add("pis_cofins", f"PIS/COFINS-Importação ({pis_cofins_pct}%)", pis_cofins_brl, "impostos_federais")
    _add("icms", f"ICMS {entradas.get('uf_destino', 'SP')} ({icms_pct}% por dentro)", icms_brl, "icms")
    _add("armazenagem", "Armazenagem Viracopos", armazenagem, "despesas_locais")
    _add("desembaraco", "Desembaraço aduaneiro", desembaraco, "despesas_locais")
    _add("thc", "THC / manuseio aéreo", thc, "despesas_locais")
    _add("siscomex", "SISCOMEX", siscomex, "despesas_locais")
    _add("frete_rod", "Frete rodoviário VCP → destino", frete_rod, "despesas_locais")

    for item in itens:
        item["pct_total"] = _pct_sobre_total(item["brl"], custo_total_brl)

    composicao = {
        "produto": round(fob_brl, 2),
        "frete_seguro": round(frete_seguro_brl, 2),
        "impostos_federais": round(impostos_federais, 2),
        "icms": round(icms_brl, 2),
        "despesas_locais": round(despesas_locais, 2),
    }

    fixa = carregar_defaults_operacao()
    return {
        "ok": True,
        "modal": "aereo_formal_cnpj",
        "aeroporto": "VCP — Viracopos",
        "destino_cep": (fixa.get("destino_entrega") or {}).get("cep", "13467-694"),
        "entradas": {
            **entradas,
            "peso_taxavel_total_kg": round(peso_taxavel_total, 3),
            "fob_usd_total": round(fob_usd * qty, 2),
            "frete_usd": round(frete_usd, 2),
        },
        "valor_aduaneiro_cif_brl": round(cif_brl, 2),
        "base_icms_brl": round(base_icms, 2),
        "ii_brl": round(ii_brl, 2),
        "ipi_brl": round(ipi_brl, 2),
        "pis_cofins_brl": round(pis_cofins_brl, 2),
        "icms_brl": round(icms_brl, 2),
        "despesas_locais_brl": round(despesas_locais, 2),
        "custo_total_brl": round(custo_total_brl, 2),
        "custo_unitario_brl": custo_unitario_brl,
        "quantidade": qty,
        "itens": itens,
        "composicao_grafico": composicao,
        "aviso_legal": fixa.get("aviso_legal")
        or "Estimativa para planejamento — confirme NCM e alíquotas com despachante.",
    }


def exportar_csv_resultado(resultado: dict[str, Any]) -> str:
    """Gera CSV do detalhamento (para salvar em arquivo ou Telegram)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["item", "grupo", "valor_brl", "pct_custo_total"])
    for item in resultado.get("itens") or []:
        w.writerow([item.get("label"), item.get("grupo"), item.get("brl"), item.get("pct_total")])
    w.writerow([])
    w.writerow(["custo_total_brl", resultado.get("custo_total_brl")])
    w.writerow(["custo_unitario_brl", resultado.get("custo_unitario_brl")])
    w.writerow(["valor_aduaneiro_cif_brl", resultado.get("valor_aduaneiro_cif_brl")])
    return buf.getvalue()


def calcular_para_produto_alibaba(
    produto: dict[str, Any],
    oportunidade: dict[str, Any],
    *,
    cambio_usd_brl: float,
) -> dict[str, Any]:
    """Atalho: produto + listing Alibaba → resultado formal."""
    entradas = montar_entradas_de_produto(produto, oportunidade, cambio_usd_brl=cambio_usd_brl)
    resultado = calcular_custo_importacao_aerea_formal(entradas)
    if resultado.get("ok"):
        resultado["produto_id"] = produto.get("id")
        resultado["produto_nome"] = produto.get("nome")
        resultado["listing_titulo"] = oportunidade.get("titulo")
        resultado["listing_url"] = oportunidade.get("url")
    return resultado
