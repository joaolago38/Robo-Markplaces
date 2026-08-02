"""Testes do contexto CNPJ × CEP × CNAE × custos aduaneiros para agentes de importação."""
from __future__ import annotations

from integracoes.importacao.contexto_importacao_cnpj import (
    CEP_TESTE_PADRAO,
    anexar_contexto_ao_resultado,
    extrair_custos_aduaneiros,
    formatar_bloco_telegram_contexto,
    montar_contexto_importacao_cnpj,
    validar_cnaes_marketplaces,
)


def test_cep_teste_padrao():
    assert CEP_TESTE_PADRAO == "13467-694"
    ctx = montar_contexto_importacao_cnpj()
    assert ctx["cep"]["destino_cep"] == "13467-694"
    assert ctx["cep"]["usando_cep_teste"] is True


def test_cnpj_cnae_marketplace_validacao():
    v = validar_cnaes_marketplaces("52668583000127")
    assert v["ok"] is True
    assert v["cnpj"] == "52668583000127"
    assert v["cnae_principal"]
    assert v["marketplaces"]["prioriza_mercadolivre"] is True
    assert "mercadolivre" in v["marketplaces"]["ativos"]


def test_custos_aduaneiros_do_calculo_formal():
    calc = {
        "ok": True,
        "valor_aduaneiro_cif_brl": 1000.0,
        "ii_brl": 100.0,
        "ipi_brl": 50.0,
        "pis_cofins_brl": 117.5,
        "icms_brl": 200.0,
        "siscomex_brl": 154.23,
        "desembaraco_brl": 1200.0,
        "armazenagem_brl": 450.0,
        "thc_brl": 380.0,
        "frete_internacional_brl": 300.0,
        "custo_total_brl": 4012.0,
        "custo_unitario_brl": 40.12,
        "itens": [
            {"id": "ii", "label": "II", "brl": 100.0, "grupo": "impostos_federais"},
            {"id": "ipi", "label": "IPI", "brl": 50.0, "grupo": "impostos_federais"},
        ],
    }
    custos = extrair_custos_aduaneiros(calc)
    assert custos["ok"] is True
    assert custos["aduaneiros"]["ii_brl"] == 100.0
    assert custos["aduaneiros"]["siscomex_brl"] == 154.23
    assert custos["total_aduaneiros_brl"] > 0
    assert custos["custo_total_brl"] == 4012.0


def test_contexto_com_responsavel_e_telegram():
    ctx = montar_contexto_importacao_cnpj(
        calculo={
            "ok": True,
            "ii_brl": 10,
            "ipi_brl": 5,
            "custo_total_brl": 500,
            "custo_unitario_brl": 5,
            "valor_aduaneiro_cif_brl": 200,
        }
    )
    assert ctx["modo"] == "importacao_cnpj"
    assert ctx["responsavel"]["nome"]
    assert ctx["cnpj"]["cnpj"] == "52668583000127"
    bloco = formatar_bloco_telegram_contexto(ctx)
    assert "13467-694" in bloco
    assert "Responsável" in bloco
    assert "Custos aduaneiros" in bloco
    assert "CNPJ" in bloco


def test_anexar_contexto_ao_resultado():
    out = anexar_contexto_ao_resultado({"ok": True, "mensagem": "teste"}, calculo=None)
    assert "contexto_importacao_cnpj" in out
    assert "bloco_telegram_importacao_cnpj" in out
    assert "13467-694" in out["mensagem"]
    assert out["contexto_importacao_cnpj"]["cnae_marketplaces"]["ok"] is True
