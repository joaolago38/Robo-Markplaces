"""Testes hub Paraguai × marketplaces (estrutura futura multi-cliente)."""
from __future__ import annotations

from integracoes.importacao.hub_paraguai_marketplace import (
    avaliar_hub_multi_cliente,
    avaliar_produto_hub_vs_marketplace,
    custos_operacao_hub,
    endereco_hub_efetivo,
    taxa_servico_cliente,
)


def test_endereco_hub_cde():
    end = endereco_hub_efetivo()
    assert end["ok"] is True
    assert end["status_hub"] == "planejado"
    assert "Ciudad del Este" in str(end["endereco"].get("cidade"))
    assert end["cep_destino_br_padrao"] == "13467-694"


def test_custos_hub_validados():
    c = custos_operacao_hub(quantidade=50, valor_carga_brl=10000.0)
    assert c["ok"] is True
    assert c["custo_hub_total_brl"] > 0
    assert c["validacao"]["volume_positivo"] is True
    assert c["validacao"]["handling_minimo_aplicado"] is True


def test_taxa_servico_terceiro():
    t = taxa_servico_cliente(1000.0)
    assert t["taxa_cobrada_brl"] >= t["minimo_brl"]
    assert t["lucro_servico_brl"] > 0


def test_produto_hub_vs_direta_e_ml():
    out = avaliar_produto_hub_vs_marketplace(
        {
            "id": "filamento-pla",
            "nome": "Filamento PLA",
            "fob_usd": 4.5,
            "peso_kg": 1.0,
            "quantidade": 50,
            "preco_venda_ml_brl": 95.0,
            "tipo_cliente": "proprio",
        },
        cambio_usd_brl=5.5,
    )
    assert out["ok"] is True
    assert out["rota_hub_py"]["custo_unitario_brl"] > 0
    assert out["rota_import_direta_br"]["custo_unitario_brl"] > 0
    assert out["veredito"]
    assert out["rota_hub_py"]["despesas_validadas"]["terrestre_py_br"] is True


def test_custo_maximo_lucro_20():
    from integracoes.importacao.hub_paraguai_marketplace import custo_maximo_para_lucro_pct

    # venda 100, taxa 16%, lucro 20% => custo max = 100*(1-0.16-0.20)=64
    t = custo_maximo_para_lucro_pct(100.0, taxa_marketplace_pct=16.0, lucro_alvo_pct=20.0)
    assert t["ok"] is True
    assert t["custo_unitario_maximo_brl"] == 64.0


def test_verificar_lucro_20_filamentos_marketplace():
    from integracoes.importacao.hub_paraguai_marketplace import verificar_hub_lucro_20_marketplace

    out = verificar_hub_lucro_20_marketplace(cambio_usd_brl=5.5, lucro_alvo_pct=20.0)
    assert out["ok"] is True
    assert out["total_produtos_marketplace"] >= 4
    assert out["lucro_alvo_pct"] == 20.0
    for v in out["verificacoes"]:
        assert "custo_hub_unitario_brl" in v
        assert "teto_custo_para_lucro_alvo" in v
        assert "quebra_custo_unitario_brl" in v
        assert v["quebra_custo_unitario_brl"]["hub_operacional"] >= 0
        # Lucro 20% agora embute tributos BR (default sem origem Mercosul)
        assert v.get("pendencia_fiscal_br_liquidada") is True
        assert v.get("cenario_tributario_decisao") == "py_sem_origem"
        assert "tributos_entrada_br" in v["quebra_custo_unitario_brl"]
        assert v["custo_hub_unitario_brl"] >= v.get("custo_hub_logistico_unitario_brl", 0)


def test_avaliar_catalogo_multi_cliente():
    out = avaliar_hub_multi_cliente(cambio_usd_brl=5.5, lucro_alvo_pct=20.0)
    assert out["ok"] is True
    assert out["total_produtos"] >= 1
    assert out["hub"]["status_hub"] == "planejado"
    assert out["lucro_alvo_pct"] == 20.0
    assert any(p.get("id") == "servico_logistico_terceiros" for p in out["possibilidades"])
    assert len(out.get("verificacao_custos_operacionais") or []) >= 1


def test_formatar_hub_py_telegram():
    from integracoes.importacao.hub_paraguai_marketplace import (
        formatar_hub_py_telegram,
        verificar_hub_lucro_20_marketplace,
    )

    assert "falhou" in formatar_hub_py_telegram({"ok": False, "motivo": "x"})
    out = verificar_hub_lucro_20_marketplace(cambio_usd_brl=5.5, lucro_alvo_pct=20.0)
    multi = avaliar_hub_multi_cliente(cambio_usd_brl=5.5, lucro_alvo_pct=20.0)
    multi["verificacao_custos_operacionais"] = out["verificacoes"]
    multi["lucrativos_marketplace_hub"] = out["atingem_lucro_alvo"]
    multi["atingem_lucro_20_com_overhead"] = out["atingem_lucro_alvo_com_overhead"]
    msg = formatar_hub_py_telegram(multi)
    assert "Hub Paraguai" in msg
    assert "CEP BR" in msg
    msg2 = formatar_hub_py_telegram({**multi, "verificacao_custos_operacionais": []})
    assert "Hub Paraguai" in msg2


def test_preco_minimo_venda_lucro():
    from integracoes.importacao.hub_paraguai_marketplace import (
        custo_maximo_para_lucro_pct,
        preco_minimo_venda_para_lucro_pct,
    )

    # custo 64, taxa 16%, lucro 20% => venda = 64 / 0.64 = 100
    p = preco_minimo_venda_para_lucro_pct(64.0, taxa_marketplace_pct=16.0, lucro_alvo_pct=20.0)
    assert p["ok"] is True
    assert p["preco_venda_minimo_brl"] == 100.0
    assert custo_maximo_para_lucro_pct(0)["ok"] is False
    assert preco_minimo_venda_para_lucro_pct(-1)["ok"] is False
    assert custo_maximo_para_lucro_pct(100, taxa_marketplace_pct=50, lucro_alvo_pct=60)["ok"] is False


def test_produto_terceiro_taxa_servico():
    out = avaliar_produto_hub_vs_marketplace(
        {
            "id": "svc",
            "nome": "Lote terceiro",
            "fob_usd": 4.0,
            "peso_kg": 1.0,
            "quantidade": 100,
            "preco_venda_ml_brl": 90.0,
            "tipo_cliente": "terceiro",
        },
        cambio_usd_brl=5.5,
    )
    assert out["ok"] is True
    assert out.get("taxa_servico_terceiro")


def test_corredor_py_terrestre_e_telegram():
    from integracoes.importacao.corredor_paraguai_terrestre import (
        formatar_py_terrestre_telegram,
        montar_cenario_py_terrestre_br,
    )

    out = montar_cenario_py_terrestre_br(
        valor_mercadoria_brl=5000.0,
        fob_usd=4.5,
        cambio_usd_brl=5.5,
        cep_destino="13467-694",
    )
    assert out["ok"] is True
    assert out.get("melhor_corredor")
    msg = formatar_py_terrestre_telegram(out)
    assert "Paraguai terrestre" in msg
    assert "indisponível" in formatar_py_terrestre_telegram({"ok": False})
    out2 = montar_cenario_py_terrestre_br(
        valor_mercadoria_brl=0,
        fob_usd=5.0,
        cambio_usd_brl=5.0,
        quantidade=10,
        cep_destino="13467-694",
    )
    assert out2["ok"] is True
