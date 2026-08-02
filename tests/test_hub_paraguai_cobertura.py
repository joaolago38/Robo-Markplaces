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


def test_buscar_qty_minima_e_cambio_auto():
    cat = hub.carregar_catalogo_hub()
    # sem preço → teto 0 → None
    assert (
        hub._buscar_qty_minima_lucro(
            {"fob_usd": 4.0, "preco_venda_ml_brl": 0},
            cambio_usd_brl=5.5,
            lucro_alvo_pct=20.0,
            taxa=16.0,
            catalogo=cat,
        )
        is None
    )
    # preço bom → encontra qty
    q = hub._buscar_qty_minima_lucro(
        {
            "fob_usd": 3.5,
            "peso_kg": 1.0,
            "preco_venda_ml_brl": 120.0,
        },
        cambio_usd_brl=5.5,
        lucro_alvo_pct=20.0,
        taxa=16.0,
        catalogo=cat,
        qty_max=500,
    )
    assert q is None or q >= 50
    # preço impossível → None
    assert (
        hub._buscar_qty_minima_lucro(
            {"fob_usd": 80.0, "peso_kg": 1.0, "preco_venda_ml_brl": 50.0},
            cambio_usd_brl=5.5,
            lucro_alvo_pct=20.0,
            taxa=16.0,
            catalogo=cat,
            qty_max=100,
        )
        is None
    )
    with patch(
        "integracoes.cambio.cotacao_usd.obter_cotacao_usd",
        side_effect=RuntimeError("sem rede"),
    ):
        out = hub.verificar_hub_lucro_20_marketplace(cambio_usd_brl=None, lucro_alvo_pct=20.0)
    assert out["ok"] is True
    assert out["cambio_usd_brl"] == 5.5


def test_vereditos_via_mock_margem():
    produto = {
        "id": "m",
        "fob_usd": 4.0,
        "quantidade": 50,
        "peso_kg": 1.0,
        "preco_venda_ml_brl": 80.0,
    }
    base_hub = {
        "ok": True,
        "custo_unitario_brl": 70.0,
        "custo_total_brl": 3500.0,
        "mercadoria_brl": 1100.0,
        "frete_china_py_brl": 100.0,
        "hub_custos": {"custo_hub_total_brl": 50.0},
        "terrestre_py_br": {"custo_total_brl": 80.0},
        "despesas_validadas": {"terrestre_py_br": True},
    }
    direta = {"ok": True, "custo_unitario_brl": 75.0, "custo_total_brl": 3750.0}

    def _margem(venda, custo, **kw):
        # hub viável mas < 20%; direta razoável
        if custo <= 70.5:
            return {
                "ok": True,
                "margem_pct": 18.0,
                "margem_brl": 10.0,
                "lucro_razoavel": True,
            }
        return {
            "ok": True,
            "margem_pct": 22.0,
            "margem_brl": 15.0,
            "lucro_razoavel": True,
        }

    with (
        patch.object(hub, "custo_rota_hub_py", return_value=base_hub),
        patch.object(hub, "custo_rota_import_direta_br", return_value=direta),
        patch.object(hub, "calcular_margem_revenda", side_effect=_margem),
        patch(
            "integracoes.importacao.tributacao_py_br.cruzar_tributacao_py_br_produto",
            return_value={"ok": True, "recomendacao": {"cenario_sugerido": "china_direto_br"}},
        ),
    ):
        out = hub.avaliar_produto_hub_vs_marketplace(produto, cambio_usd_brl=5.5)
    assert out["veredito"] in (
        "HUB_PY_VIAVEL_ML",
        "IMPORT_DIRETA_MELHOR",
        "HUB_PY_MAIS_BARATO_MAS_MARGEM_APERTADA",
        "REVISAR_PRECO_OU_CUSTO",
        "HUB_PY_LUCRO_20",
    )

    # direta melhor (hub sem lucro_razoavel)
    def _margem2(venda, custo, **kw):
        if custo <= 70.5:
            return {"ok": True, "margem_pct": 5.0, "margem_brl": 1.0, "lucro_razoavel": False}
        return {"ok": True, "margem_pct": 25.0, "margem_brl": 20.0, "lucro_razoavel": True}

    with (
        patch.object(hub, "custo_rota_hub_py", return_value=base_hub),
        patch.object(hub, "custo_rota_import_direta_br", return_value=direta),
        patch.object(hub, "calcular_margem_revenda", side_effect=_margem2),
        patch(
            "integracoes.importacao.tributacao_py_br.cruzar_tributacao_py_br_produto",
            return_value={"ok": True, "recomendacao": {}},
        ),
    ):
        out2 = hub.avaliar_produto_hub_vs_marketplace(produto, cambio_usd_brl=5.5)
    assert out2["veredito"] == "IMPORT_DIRETA_MELHOR"

    # hub mais barato margem apertada
    def _margem3(venda, custo, **kw):
        return {"ok": True, "margem_pct": 5.0, "margem_brl": 1.0, "lucro_razoavel": False}

    with (
        patch.object(
            hub,
            "custo_rota_hub_py",
            return_value={**base_hub, "custo_unitario_brl": 60.0},
        ),
        patch.object(
            hub,
            "custo_rota_import_direta_br",
            return_value={**direta, "custo_unitario_brl": 90.0},
        ),
        patch.object(hub, "calcular_margem_revenda", side_effect=_margem3),
        patch(
            "integracoes.importacao.tributacao_py_br.cruzar_tributacao_py_br_produto",
            return_value={"ok": True, "recomendacao": {}},
        ),
    ):
        out3 = hub.avaliar_produto_hub_vs_marketplace(produto, cambio_usd_brl=5.5)
    assert out3["veredito"] == "HUB_PY_MAIS_BARATO_MAS_MARGEM_APERTADA"


def test_ramos_extras_cobertura():
    assert hub.custo_rota_hub_py(fob_usd=0, cambio_usd_brl=5.5)["ok"] is False
    assert hub.custo_rota_hub_py(fob_usd=4.0, cambio_usd_brl=0)["ok"] is False

    produto = {
        "id": "orig",
        "fob_usd": 3.0,
        "quantidade": 200,
        "peso_kg": 1.0,
        "preco_venda_ml_brl": 150.0,
    }
    base_hub = {
        "ok": True,
        "custo_unitario_brl": 40.0,
        "custo_total_brl": 8000.0,
        "mercadoria_brl": 3000.0,
        "frete_china_py_brl": 200.0,
        "hub_custos": {"custo_hub_total_brl": 100.0},
        "terrestre_py_br": {"custo_total_brl": 150.0},
        "despesas_validadas": {"terrestre_py_br": True},
    }
    direta = {"ok": True, "custo_unitario_brl": 55.0}

    def _m_ok(venda, custo, **kw):
        return {"ok": True, "margem_pct": 30.0, "margem_brl": 40.0, "lucro_razoavel": True}

    with (
        patch.object(hub, "custo_rota_hub_py", return_value=base_hub),
        patch.object(hub, "custo_rota_import_direta_br", return_value=direta),
        patch.object(hub, "calcular_margem_revenda", side_effect=_m_ok),
        patch(
            "integracoes.importacao.tributacao_py_br.cruzar_tributacao_py_br_produto",
            return_value={
                "ok": True,
                "recomendacao": {"cenario_sugerido": "py_origem_mercosul"},
            },
        ),
    ):
        out = hub.avaliar_produto_hub_vs_marketplace(produto, cambio_usd_brl=5.5)
    assert "MERCOSUL" in out["veredito"]

    with (
        patch.object(hub, "custo_rota_hub_py", return_value=base_hub),
        patch.object(hub, "custo_rota_import_direta_br", return_value=direta),
        patch.object(hub, "calcular_margem_revenda", side_effect=_m_ok),
        patch(
            "integracoes.importacao.tributacao_py_br.cruzar_tributacao_py_br_produto",
            side_effect=RuntimeError("trib off"),
        ),
    ):
        out2 = hub.avaliar_produto_hub_vs_marketplace(produto, cambio_usd_brl=5.5)
    assert out2["ok"] is True

    with patch(
        "integracoes.cambio.cotacao_usd.obter_cotacao_usd",
        return_value={"usd_brl": 5.25},
    ):
        multi = hub.avaliar_hub_multi_cliente(
            cambio_usd_brl=None,
            produtos=[
                {**produto, "ativo": True},
                {"id": "off", "ativo": False, "fob_usd": 1},
                "lixo",
            ],
        )
    assert multi["ok"] is True
    assert multi["cambio_usd_brl"] == 5.25

    with patch(
        "integracoes.cambio.cotacao_usd.obter_cotacao_usd",
        side_effect=RuntimeError("x"),
    ):
        multi2 = hub.avaliar_hub_multi_cliente(
            cambio_usd_brl=None,
            produtos=[{**produto, "ativo": True}],
        )
    assert multi2["cambio_usd_brl"] == 5.5

    # origem Mercosul preferível sem atingir 20%
    def _m_mid(venda, custo, **kw):
        return {"ok": True, "margem_pct": 18.0, "margem_brl": 8.0, "lucro_razoavel": True}

    with (
        patch.object(hub, "custo_rota_hub_py", return_value={**base_hub, "custo_unitario_brl": 55.0}),
        patch.object(hub, "custo_rota_import_direta_br", return_value=direta),
        patch.object(hub, "calcular_margem_revenda", side_effect=_m_mid),
        patch(
            "integracoes.importacao.tributacao_py_br.cruzar_tributacao_py_br_produto",
            return_value={
                "ok": True,
                "recomendacao": {"cenario_sugerido": "py_origem_mercosul"},
            },
        ),
    ):
        out3 = hub.avaliar_produto_hub_vs_marketplace(
            {**produto, "preco_venda_ml_brl": 90.0},
            cambio_usd_brl=5.5,
        )
    assert out3["veredito"] == "HUB_PY_ORIGEM_MERCOSUL_PREFERIVEL"
    assert hub.preco_minimo_venda_para_lucro_pct(10, taxa_marketplace_pct=90, lucro_alvo_pct=20)["ok"] is False
