"""Testes contexto importação filamento 3D (Masterprint + Siscomex vigente)."""
from __future__ import annotations

from integracoes.filamentos.contexto_importacao_filamento import (
    CNPJ_FILAMENTO,
    cep_destino_filamento,
    enriquecer_produto_filamento_alibaba,
    params_landed_filamento,
)
from integracoes.filamentos.sourcing_filamentos import analisar_material


def test_cnpj_masterprint_e_cep():
    assert CNPJ_FILAMENTO == "23811261000197"
    assert cep_destino_filamento() == "13467-694"


def test_params_siscomex_vigente():
    p = params_landed_filamento({"material": "PLA", "ii_pct": 12.6})
    assert p["siscomex_brl"] == 154.23
    assert p["siscomex_adicoes"] == 1
    assert p["afrmm_pct"] > 0
    assert p["cnpj_importador"] == "23811261000197"
    assert p["cep_destino"] == "13467-694"


def test_enriquecer_catalogo_filamento():
    out = enriquecer_produto_filamento_alibaba(
        {"id": "filamento-impressora-3d-pla", "ativo": True, "material": "PLA", "ncm": "39169090"}
    )
    assert out["empresa_id"] == "masterprint"
    assert out["siscomex_brl"] == 154.23
    assert out["importacao_params"]["pis_pct"] == 2.1


def test_analisar_material_inclui_siscomex_e_afrmm():
    out = analisar_material(
        "PLA",
        fornecedor_br={
            "id": "br-pla",
            "fornecedor": "Dist BR",
            "custo_unitario_brl": 40.0,
            "peso_kg": 1.0,
        },
        precos_ml={"preco_min": 80.0, "preco_medio": 95.0, "preco_max": 110.0},
        cambio_usd_brl=5.5,
        fob_usd=4.0,
        moq_china=20,
    )
    china = out["china"]
    assert china["siscomex_brl"] == 154.23
    assert china["despesas_aduaneiras_inclusas"] is True
    assert china["impostos_maritimo"] is not None
    assert china["impostos_maritimo"]["afrmm_brl"] > 0
    assert out["cnpj_importador"] == "23811261000197"
    assert out["cep_destino"] == "13467-694"
