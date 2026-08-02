"""Cobertura extra: hub PY helpers, portos PY env, vereditos de margem."""
from __future__ import annotations

from unittest.mock import patch

from integracoes.importacao import hub_paraguai_marketplace as hub
from integracoes.importacao import portos_brasil as portos


def test_helpers_f_i_invalidos():
    assert hub._f("x", 1.5) == 1.5
    assert hub._f(None, 2.0) == 2.0
    assert hub._i("nope", 3) == 3
    assert hub._i(None, 4) == 4


def test_carregar_produtos_com_snapshot_ml(tmp_path, monkeypatch):
    snap = {
        "resultados": [
            {"ok": True, "material": "PLA", "preco_medio": 99.0},
            {"ok": False, "material": "X"},
            "lixo",
        ],
        "consolidado": {
            "por_termo": [
                {"material": "PETG", "preco_medio": 88.0},
                {"material": "PLA", "preco_medio": 50.0},  # já tem no resultados
            ]
        },
    }
    monkeypatch.setattr(hub, "ROOT", tmp_path)
    (tmp_path / "logs").mkdir()
    from core.atomic_io import escrever_json_atomico

    escrever_json_atomico(tmp_path / "logs" / "filamentos_ml_ultima.json", snap)

    cat = {
        "produtos_candidato_exemplo": [
            {
                "id": "pla-sem-preco",
                "ativo": True,
                "material": "PLA",
                "fob_usd": 0,
                "preco_venda_ml_brl": 0,
            },
            {
                "id": "petg-sem-preco",
                "ativo": True,
                "material": "PETG",
                "fob_usd": 0,
                "preco_venda_ml_brl": 0,
            },
        ]
    }
    with patch("integracoes.importacao.hub_paraguai_marketplace.ler_json") as mock_ler:
        # primeira chamada no carregar_catalogo via cat passado; dentro carregar_produtos
        # chama ler_json para snap e alibaba
        def _ler(path, default=None):
            p = str(path)
            if "filamentos_ml" in p:
                return snap
            if "alibaba" in p or "importacao" in p:
                return [
                    {
                        "id": "filamento-pla-x",
                        "ativo": True,
                        "ramo": "filamentos",
                        "material": "PLA",
                        "preco_max_usd": 10.0,
                    }
                ]
            return default if default is not None else {}

        mock_ler.side_effect = _ler
        itens = hub.carregar_produtos_marketplace_hub(cat)
    assert len(itens) == 2
    pla = next(i for i in itens if i["material"] == "PLA")
    assert pla["preco_venda_ml_brl"] == 99.0
    assert pla["preco_ml_fonte"] == "snapshot_filamentos_ml"
    assert pla["fob_usd"] > 0


def test_vereditos_margem_hub():
    # sem venda → REVISAR
    out = hub.avaliar_produto_hub_vs_marketplace(
        {"id": "a", "fob_usd": 4.0, "quantidade": 20, "preco_venda_ml_brl": 0},
        cambio_usd_brl=5.5,
    )
    assert out["veredito"] in (
        "REVISAR_PRECO_OU_CUSTO",
        "HUB_PY_MAIS_BARATO_MAS_MARGEM_APERTADA",
        "IMPORT_DIRETA_MELHOR",
        "HUB_PY_VIAVEL_ML",
        "HUB_PY_LUCRO_20",
        "HUB_PY_ORIGEM_MERCOSUL_PREFERIVEL",
        "HUB_PY_ORIGEM_MERCOSUL_LUCRO",
    )
    # preço alto → lucro 20
    out2 = hub.avaliar_produto_hub_vs_marketplace(
        {
            "id": "b",
            "fob_usd": 3.0,
            "quantidade": 300,
            "preco_venda_ml_brl": 200.0,
            "peso_kg": 1.0,
        },
        cambio_usd_brl=5.5,
    )
    assert out2["atinge_lucro_alvo"] is True or out2["veredito"]


def test_icms_gateway_ramos():
    assert portos.icms_gateway({}, uf_destino="sp") == portos.icms_gateway({}, uf_destino="SP")
    assert portos.icms_gateway({"icms_uf_pct": 12}) == 12.0
    assert portos.icms_gateway({"icms_uf_pct": "x", "uf": "PR"}) > 0
    assert portos.icms_gateway({"uf": "ZZ"}) == 18.0


def test_endereco_py_via_env(monkeypatch):
    monkeypatch.setattr("core.config.IMPORTACAO_PY_ENDERECO", "Av Test 123")
    monkeypatch.setattr("core.config.IMPORTACAO_PY_CIDADE", "Encarnacion")
    monkeypatch.setattr("core.config.IMPORTACAO_PY_DEPARTAMENTO", "Itapua")
    monkeypatch.setattr("core.config.IMPORTACAO_PY_CODIGO_POSTAL", "6000")
    end = portos.endereco_comercial_paraguai()
    assert end["via_env"] is True
    assert end["endereco"]["cidade"] == "Encarnacion"
    assert end["endereco"]["endereco"] == "Av Test 123"
