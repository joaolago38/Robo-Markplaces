"""Testes cruzamento tributário Paraguai × Brasil (Mercosul)."""
from __future__ import annotations

from integracoes.importacao.tributacao_py_br import (
    cruzar_tributacao_py_br_produto,
    tributos_entrada_brasil_desde_py,
    tributos_lado_paraguai,
)


def test_iva_exportacao_py_zerado():
    t = tributos_lado_paraguai(10000.0, exportacao_para_br=True)
    assert t["ok"] is True
    assert t["iva_brl"] == 0.0
    assert t["total_tributos_py_brl"] == 0.0


def test_maquila_1pct_va():
    t = tributos_lado_paraguai(
        10000.0,
        exportacao_para_br=True,
        regime_maquila=True,
        valor_agregado_py_brl=4000.0,
        maquila_pct=1.0,
    )
    assert t["maquila_brl"] == 40.0


def test_ii_zero_com_origem_mercosul():
    com = tributos_entrada_brasil_desde_py(1000.0, com_certificado_origem_mercosul=True)
    sem = tributos_entrada_brasil_desde_py(
        1000.0, com_certificado_origem_mercosul=False, ii_pct_sem_origem=16.0
    )
    assert com["ii_pct"] == 0.0
    assert com["ii_brl"] == 0.0
    assert sem["ii_brl"] == 160.0
    assert com["custo_apos_tributos_brl"] < sem["custo_apos_tributos_brl"]
    assert com["economia_ii_vs_cheia_brl"] == 160.0
    # PIS/COFINS e ICMS permanecem; desembaraço default embutido
    assert com["pis_cofins_brl"] > 0
    assert com["icms_brl"] > 0
    assert com["despesas_locais_brl"] > 0


def test_default_entrada_py_sem_origem():
    """Default = II cheio (trânsito CN→PY não zera II)."""
    d = tributos_entrada_brasil_desde_py(1000.0, ii_pct_sem_origem=12.6)
    assert d["com_certificado_origem_mercosul"] is False
    assert d["ii_brl"] == 126.0


def test_cruzar_origem_mais_barata_que_sem_origem():
    out = cruzar_tributacao_py_br_produto(
        fob_usd=4.5,
        cambio_usd_brl=5.5,
        quantidade=200,
        frete_internacional_brl=500.0,
        ii_pct_china=12.6,
        preco_venda_ml_brl=95.0,
        lucro_alvo_pct=20.0,
        custos_logistica_py_br_unit=3.0,
        origem_qualificada_mercosul=False,
    )
    assert out["ok"] is True
    by = {c["cenario"]: c for c in out["cenarios"]}
    assert by["py_origem_mercosul"]["custo_unitario_brl"] < by["py_sem_origem"]["custo_unitario_brl"]
    assert by["py_origem_mercosul"]["elegivel_decisao"] is False
    assert by["py_sem_origem"]["elegivel_decisao"] is True
    assert out["cenario_decisao_py"] == "py_sem_origem"
    assert out["melhor_custo"] in ("py_sem_origem", "china_direto_br")
    assert out["recomendacao"]["cenario_sugerido"]


def test_cruzar_com_origem_qualificada_elegivel():
    out = cruzar_tributacao_py_br_produto(
        fob_usd=4.5,
        cambio_usd_brl=5.5,
        quantidade=200,
        frete_internacional_brl=500.0,
        ii_pct_china=12.6,
        preco_venda_ml_brl=95.0,
        origem_qualificada_mercosul=True,
    )
    assert out["cenario_decisao_py"] == "py_origem_mercosul"
    by = {c["cenario"]: c for c in out["cenarios"]}
    assert by["py_origem_mercosul"]["elegivel_decisao"] is True


def test_avaliar_catalogo_filamentos_trib():
    from integracoes.importacao.tributacao_py_br import avaliar_tributacao_produtos_marketplace

    out = avaliar_tributacao_produtos_marketplace(cambio_usd_brl=5.5, lucro_alvo_pct=20.0)
    assert out["ok"] is True
    assert out["total_produtos"] >= 4
    # Com origem Mercosul (II=0) sempre bate PY sem certificado
    assert out["origem_melhor_que_sem_certificado"] == out["total_produtos"]
    for a in out["analises"]:
        assert a["origem_melhor_que_sem_certificado"] is True


def test_iva_venda_interna_py():
    t = tributos_lado_paraguai(1000.0, exportacao_para_br=False, iva_pct=10.0)
    assert t["iva_brl"] == 100.0


def test_cruzar_preco_invalido():
    out = cruzar_tributacao_py_br_produto(fob_usd=0, preco_origem_py_brl=0)
    assert out["ok"] is False


def test_formatar_trib_telegram():
    from integracoes.importacao.tributacao_py_br import (
        avaliar_tributacao_produtos_marketplace,
        formatar_tributacao_py_br_telegram,
    )

    assert "x" in formatar_tributacao_py_br_telegram({"ok": False, "motivo": "x"})
    out = avaliar_tributacao_produtos_marketplace(cambio_usd_brl=5.5, lucro_alvo_pct=20.0)
    msg = formatar_tributacao_py_br_telegram(out)
    assert "Tributação Paraguai" in msg
    assert "origem > sem cert." in msg


def test_cruzar_preco_origem_py_brl():
    out = cruzar_tributacao_py_br_produto(
        preco_origem_py_brl=25.0,
        quantidade=100,
        frete_internacional_brl=200.0,
        ii_pct_china=12.6,
        preco_venda_ml_brl=80.0,
        custos_logistica_py_br_unit=2.0,
        regime_maquila=True,
    )
    assert out["ok"] is True
    assert out["fonte_preco"] == "preco_py_brl"


def test_origem_bate_sem_vazio():
    from integracoes.importacao.tributacao_py_br import _origem_bate_sem

    assert _origem_bate_sem({}) is False
    assert _origem_bate_sem({"cenarios": [{"cenario": "py_origem_mercosul", "custo_unitario_brl": 10}]}) is False
