"""
integracoes/leilao/comparacao_fipe.py
Compara lance de leilão + taxas com a Tabela FIPE (vantagem = FIPE − custo total).
"""
from __future__ import annotations

import logging
from typing import Any

from core.config import (
    LEILAO_COMISSAO_PCT,
    LEILAO_FIPE_HAIRCUT_SINISTRO_PCT,
    LEILAO_LAUDO_BRL,
    LEILAO_MARGEM_FIPE_MIN_PCT,
    LEILAO_MARGEM_FIPE_MIN_REAIS,
    LEILAO_PRECO_MAX_LANCE,
    LEILAO_REMOCAO_ESTADIA_BRL,
    LEILAO_TAXA_ADMIN_BRL,
    LEILAO_TAXA_CADASTRO_BRL,
)
from integracoes.veiculos.fipe_client import consultar_preco_fipe, parse_valor_fipe

logger = logging.getLogger("leilao_comparacao_fipe")

_SINISTRO_TOKENS = (
    "sinistro",
    "sinistrado",
    "batido",
    "recuperado",
    "salvado",
    "sucata",
    "perda total",
    "pt ",
    " pt",
    "monta",
    "classificação",
)


def _parece_sinistro(texto: str) -> bool:
    t = (texto or "").lower()
    return any(tok in t for tok in _SINISTRO_TOKENS)


def aplicar_haircut_fipe(
    valor_fipe: float,
    *,
    texto_contexto: str = "",
    haircut_pct: float | None = None,
) -> dict[str, float | bool]:
    """Reduz FIPE de tabela limpa quando o contexto indica sinistro/recuperado."""
    pct = LEILAO_FIPE_HAIRCUT_SINISTRO_PCT if haircut_pct is None else float(haircut_pct)
    pct = max(0.0, min(90.0, pct))
    sinistro = _parece_sinistro(texto_contexto)
    if not sinistro or pct <= 0 or valor_fipe <= 0:
        return {
            "valor_fipe_ajustado": round(float(valor_fipe), 2),
            "fipe_haircut_pct": 0.0,
            "fipe_sinistro": False,
        }
    ajustado = float(valor_fipe) * (1.0 - pct / 100.0)
    return {
        "valor_fipe_ajustado": round(ajustado, 2),
        "fipe_haircut_pct": pct,
        "fipe_sinistro": True,
    }


def parse_valor_leilao(valor: Any) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        v = float(valor)
        return v if v > 0 else None
    v = parse_valor_fipe(str(valor))
    return v if v > 0 else None


def calcular_custo_leilao_total(
    lance_brl: float,
    *,
    comissao_pct: float | None = None,
    taxa_cadastro_brl: float | None = None,
    taxa_admin_brl: float | None = None,
    remocao_estadia_brl: float | None = None,
    laudo_brl: float | None = None,
) -> dict[str, Any]:
    """
    Custo total estimado = lance + comissão leiloeiro + taxas fixas do leilão.
    """
    comissao_pct = LEILAO_COMISSAO_PCT if comissao_pct is None else comissao_pct
    taxa_cadastro = LEILAO_TAXA_CADASTRO_BRL if taxa_cadastro_brl is None else taxa_cadastro_brl
    taxa_admin = LEILAO_TAXA_ADMIN_BRL if taxa_admin_brl is None else taxa_admin_brl
    remocao = LEILAO_REMOCAO_ESTADIA_BRL if remocao_estadia_brl is None else remocao_estadia_brl
    laudo = LEILAO_LAUDO_BRL if laudo_brl is None else laudo_brl

    comissao = lance_brl * (comissao_pct / 100.0)
    taxas_fixas = taxa_cadastro + taxa_admin + remocao + laudo
    custo_total = lance_brl + comissao + taxas_fixas

    return {
        "lance_brl": round(lance_brl, 2),
        "comissao_leiloeiro_pct": comissao_pct,
        "comissao_leiloeiro_brl": round(comissao, 2),
        "taxa_cadastro_brl": round(taxa_cadastro, 2),
        "taxa_admin_brl": round(taxa_admin, 2),
        "remocao_estadia_brl": round(remocao, 2),
        "laudo_brl": round(laudo, 2),
        "taxas_fixas_brl": round(taxas_fixas, 2),
        "custo_total_brl": round(custo_total, 2),
    }


def calcular_vantagem_fipe(*, valor_fipe: float, custo_total_brl: float) -> dict[str, float]:
    if valor_fipe <= 0:
        return {"margem_fipe_reais": 0.0, "margem_fipe_pct": 0.0}
    margem_reais = valor_fipe - custo_total_brl
    margem_pct = (margem_reais / valor_fipe) * 100.0
    return {
        "margem_fipe_reais": round(margem_reais, 2),
        "margem_fipe_pct": round(margem_pct, 2),
    }


def avaliar_achado_leilao(
    achado: dict[str, Any],
    veiculo: dict[str, Any],
    *,
    margem_min_pct: float | None = None,
    margem_min_reais: float | None = None,
    preco_max_lance: float | None = None,
) -> dict[str, Any]:
    """
    Enriquece achado com FIPE, custo total do leilão e flag vantajoso.
    """
    margem_min_pct = LEILAO_MARGEM_FIPE_MIN_PCT if margem_min_pct is None else margem_min_pct
    margem_min_reais = LEILAO_MARGEM_FIPE_MIN_REAIS if margem_min_reais is None else margem_min_reais
    preco_max = LEILAO_PRECO_MAX_LANCE if preco_max_lance is None else preco_max_lance

    out = dict(achado)
    lance = parse_valor_leilao(achado.get("valor"))
    if lance is None:
        out["analise_fipe"] = {"ok": False, "motivo": "valor do lance não identificado"}
        out["vantajoso"] = False
        return out

    if preco_max > 0 and lance > preco_max:
        out["analise_fipe"] = {"ok": False, "motivo": f"lance acima do máximo (R$ {preco_max:,.0f})"}
        out["lance_brl"] = lance
        out["vantajoso"] = False
        return out

    custo = calcular_custo_leilao_total(lance)
    out["lance_brl"] = lance
    out.update(custo)

    titulo = str(achado.get("titulo") or "")
    ano_texto = str(achado.get("ano") or titulo)
    fipe = consultar_preco_fipe(
        marca=str(achado.get("marca") or veiculo.get("marca") or ""),
        titulo=titulo,
        ano_texto=ano_texto,
        modelo_hint=str(veiculo.get("modelo") or achado.get("modelo") or ""),
    )
    if not fipe:
        out["analise_fipe"] = {"ok": False, "motivo": "FIPE indisponível para este veículo/ano"}
        out["vantajoso"] = False
        return out

    out.update(fipe)
    contexto = f"{titulo} {achado.get('condicao') or ''} {achado.get('observacao') or ''}"
    haircut = aplicar_haircut_fipe(float(fipe["valor_fipe"]), texto_contexto=contexto)
    valor_fipe_uso = float(haircut["valor_fipe_ajustado"])
    out["valor_fipe_tabela"] = float(fipe["valor_fipe"])
    out["valor_fipe"] = valor_fipe_uso
    out["fipe_haircut_pct"] = haircut["fipe_haircut_pct"]
    out["fipe_sinistro"] = haircut["fipe_sinistro"]
    margem = calcular_vantagem_fipe(valor_fipe=valor_fipe_uso, custo_total_brl=custo["custo_total_brl"])
    out.update(margem)
    vantajoso = margem["margem_fipe_pct"] >= margem_min_pct and margem["margem_fipe_reais"] >= margem_min_reais
    out["vantajoso"] = vantajoso
    out["analise_fipe"] = {
        "ok": True,
        "vantajoso": vantajoso,
        "margem_min_pct": margem_min_pct,
        "margem_min_reais": margem_min_reais,
        "fipe_sinistro": haircut["fipe_sinistro"],
        "fipe_haircut_pct": haircut["fipe_haircut_pct"],
    }
    return out


def filtrar_vantajosos(achados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resultado = [a for a in achados if a.get("vantajoso")]
    resultado.sort(key=lambda x: float(x.get("margem_fipe_pct") or 0), reverse=True)
    return resultado
