"""Testes Taxa de Utilização do Siscomex (Portaria ME 4.131/2021)."""
from __future__ import annotations

from integracoes.importacao.siscomex import (
    SISCOMEX_DI_BRL,
    SISCOMEX_LEGADO_DI_1_ADICAO_BRL,
    calcular_taxa_siscomex,
    taxa_siscomex_brl,
)
from integracoes.importacao.custo_landed import calcular_custo_landed


def test_di_uma_adicao_valor_vigente():
    out = calcular_taxa_siscomex(adicoes=1)
    assert out["ok"] is True
    assert out["di_brl"] == 115.67
    assert out["adicoes_brl"] == 38.56
    assert out["total_brl"] == 154.23
    assert out["total_brl"] != SISCOMEX_LEGADO_DI_1_ADICAO_BRL


def test_faixas_adicoes_decrescentes():
    # 1ª e 2ª = 38.56; 3ª = 30.85
    out = calcular_taxa_siscomex(adicoes=3)
    assert out["total_brl"] == round(115.67 + 38.56 + 38.56 + 30.85, 2)
    assert out["detalhe_adicoes"][2]["brl"] == 30.85


def test_atalho_taxa_siscomex_brl():
    assert taxa_siscomex_brl(adicoes=1) == 154.23
    assert SISCOMEX_DI_BRL == 115.67


def test_landed_substitui_legado_214_50():
    out = calcular_custo_landed(
        2.0,
        cambio_usd_brl=5.0,
        quantidade=10,
        modo_frete="aereo",
        siscomex_brl=214.50,  # legado — deve recalcular
        siscomex_adicoes=1,
    )
    assert out["ok"] is True
    assert out["siscomex_brl"] == 154.23
    assert out["siscomex_detalhe"]["total_brl"] == 154.23
