"""
tests/test_cenario_macro.py
Funções puras do cenário e o agente desligado (sem rede, sem logs reais).
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.config as cfg
from core.cenario_macro import (
    custo_carregamento_estoque,
    custo_reposicao,
    margem_exigida_pct,
    recomendar_sku,
    regime_cambial,
)
from integracoes.importacao.analise_margem import calcular_sensibilidade_cambio

_BASE = {1: 10.0, 2: 18.0, 3: 25.0}
_FRENTE = ("IMP-MIMO-003", "IMP-PERL-004", "IMP-JUPAES-006")


class RegimeCambialTests(unittest.TestCase):
    def test_sem_referencia(self):
        self.assertEqual(regime_cambial(5.2, 0)["regime"], "sem_referencia")

    def test_calmo(self):
        out = regime_cambial(5.0 * 1.01, 5.0)
        self.assertEqual(out["regime"], "calmo")
        self.assertAlmostEqual(out["variacao_pct"], 1.0, places=2)

    def test_estresse(self):
        self.assertEqual(regime_cambial(5.0 * 1.05, 5.0)["regime"], "estresse")

    def test_choque(self):
        self.assertEqual(regime_cambial(5.0 * 1.10, 5.0)["regime"], "choque")

    def test_cotacao_invalida(self):
        self.assertEqual(regime_cambial(0, 5.0)["regime"], "sem_referencia")
        self.assertEqual(regime_cambial(-1, 5.0)["regime"], "sem_referencia")


class MargemExigidaTests(unittest.TestCase):
    def test_inativo_devolve_a_base(self):
        self.assertEqual(margem_exigida_pct(2, _BASE, 5, False), 18.0)

    def test_ativo_soma_pp(self):
        self.assertEqual(margem_exigida_pct(1, _BASE, 2, True), 12.0)

    def test_pp_negativo_e_ignorado(self):
        self.assertEqual(margem_exigida_pct(3, _BASE, -4, True), 25.0)

    def test_teto_de_60(self):
        self.assertEqual(margem_exigida_pct(3, _BASE, 80, True), 60.0)


class CustoTests(unittest.TestCase):
    def test_reposicao(self):
        self.assertEqual(custo_reposicao(10.0, 10), 11.0)
        self.assertEqual(custo_reposicao(10.0, -3), 10.0)

    def test_carregamento(self):
        # 100 * 1,2% * 30/30 = 1,20
        self.assertEqual(custo_carregamento_estoque(100.0, 30, 1.2), 1.2)
        self.assertEqual(custo_carregamento_estoque(100.0, 0, 1.2), 0.0)


class RecomendarSkuTests(unittest.TestCase):
    def _rec(self, **kwargs):
        base = dict(
            sku="IMP-X",
            custo_total=20.0,
            custo_reposicao_unit=20.0,
            preco_atual=50.0,
            taxa_canal_pct=18.0,
            fase=1,
            estoque=100,
            vendas_dia=5.0,
            margem_exigida=15.0,
            cobertura_alvo_dias=45,
            custo_capital_mes_pct=1.2,
        )
        base.update(kwargs)
        return recomendar_sku(**base)

    def test_manter(self):
        self.assertEqual(self._rec()["acao"], "manter")

    def test_subir_preco_na_reposicao(self):
        out = self._rec(custo_reposicao_unit=45.0)
        self.assertEqual(out["acao"], "subir_preco_na_reposicao")
        self.assertLess(out["margem_na_reposicao_pct"], 15.0)

    def test_antecipar_compra(self):
        # cobertura 10d < 45; ganho R$ 4 > carregamento de 45 dias
        out = self._rec(custo_reposicao_unit=24.0, estoque=50, vendas_dia=5.0)
        self.assertEqual(out["acao"], "antecipar_compra")

    def test_antecipar_nao_quando_carregamento_supera_ganho(self):
        out = self._rec(
            custo_total=100.0,
            custo_reposicao_unit=100.5,
            preco_atual=160.0,
            estoque=50,
            vendas_dia=5.0,
        )
        self.assertNotEqual(out["acao"], "antecipar_compra")
        self.assertEqual(out["acao"], "manter")

    def test_nao_repor_sem_giro(self):
        out = self._rec(estoque=200, vendas_dia=1.0)
        self.assertEqual(out["acao"], "nao_repor_sem_giro")

    def test_revisar_dados(self):
        self.assertEqual(self._rec(preco_atual=0)["acao"], "revisar_dados")
        self.assertEqual(self._rec(custo_total=0)["acao"], "revisar_dados")


class RepricingCenarioTests(unittest.TestCase):
    def _kits_frente(self):
        from core.catalogo_produtos import carregar_produtos_catalogo

        por_sku = {p.get("sku"): p for p in carregar_produtos_catalogo()}
        return [por_sku[sku] for sku in _FRENTE]

    def test_desligado_igual_a_formula_anterior(self):
        from agentes.repricing.agente_repricing_impala import TAXA_ML, calcular_preco_ideal

        self.assertAlmostEqual(TAXA_ML, 0.18)
        with patch.object(cfg, "CENARIO_MACRO_ATIVO", False):
            for kit in self._kits_frente():
                fase = int(kit.get("fase_atual") or 1)
                margem = {1: 0.10, 2: 0.18, 3: 0.25}[fase]
                custo = float(kit.get("custo_total") or 0)
                piso = custo / (1 - 0.18 - margem)
                preco_fase = float((kit.get("precos_por_fase") or {}).get(f"fase{fase}", piso))
                esperado = round(max(preco_fase, piso), 2)
                out = calcular_preco_ideal(kit)
                self.assertEqual(out["preco_sugerido"], esperado, kit.get("sku"))
                self.assertFalse(out["cenario_macro"])
                self.assertNotIn("aviso", out)

    def test_reposicao_sobe_preco_e_congelado_avisa(self):
        from agentes.repricing.agente_repricing_impala import calcular_preco_ideal

        perl = next(k for k in self._kits_frente() if k.get("sku") == "IMP-PERL-004")
        with patch.object(cfg, "CENARIO_MACRO_ATIVO", False):
            antes = calcular_preco_ideal(perl)["preco_sugerido"]
        with (
            patch.object(cfg, "CENARIO_MACRO_ATIVO", True),
            patch.object(cfg, "CENARIO_REPOSICAO_ALTA_PCT", 10.0),
            patch.object(cfg, "CENARIO_MARGEM_ADICIONAL_PP", 0.0),
        ):
            depois = calcular_preco_ideal(perl)
        self.assertGreater(depois["preco_sugerido"], antes)

        congelado = {
            "sku": "IMP-MIMO-003",
            "custo_total": 40.0,
            "fase_atual": 1,
            "preco": 44.9,
            "precos_por_fase": {"fase1": 44.9},
            "canais": {"mercadolivre": {"preco": 44.9}},
        }
        with (
            patch.object(cfg, "CENARIO_MACRO_ATIVO", True),
            patch.object(cfg, "CENARIO_REPOSICAO_ALTA_PCT", 10.0),
            patch.object(cfg, "CENARIO_MARGEM_ADICIONAL_PP", 0.0),
            patch(
                "agentes.repricing.agente_repricing_impala._precos_congelados",
                return_value={"IMP-MIMO-003"},
            ),
        ):
            out = calcular_preco_ideal(congelado)
        self.assertEqual(out["preco_sugerido"], 44.9)
        self.assertFalse(out["ajuste_necessario"])
        self.assertEqual(out["aviso"], "piso_acima_do_congelado")


class SensibilidadeCambioTests(unittest.TestCase):
    def test_margem_cai_quando_dolar_sobe(self):
        produto = {
            "id": "p1",
            "nome": "Filamento PLA",
            "peso_kg": 1,
            "preco_usd": 3.5,
            "moq": 100,
            "preco_venda_brl": 75.0,
            "margem_minima_pct": 10,
            "margem_minima_reais": 3,
        }
        cenarios = calcular_sensibilidade_cambio(produto, 5.5, (0, 5, 10))
        margens = [c["margem_pct"] for c in cenarios]
        self.assertEqual(len(margens), 3)
        self.assertTrue(all(m is not None for m in margens))
        self.assertGreater(margens[0], margens[1])
        self.assertGreater(margens[1], margens[2])


class AgenteAtivoTests(unittest.TestCase):
    def test_grava_snapshot_sem_rede_real(self):
        from agentes.precificacao import agente_cenario_macro as ag

        produtos = [
            {
                "sku": "IMP-PERL-004",
                "nome": "Perl",
                "prioridade": "P0",
                "fase_atual": 1,
                "custo_total": 26.23,
                "frete_estimado": 11.0,
                "peso_gramas": 380,
                "preco": 39.9,
                "vd_dia_ml_ref": 2,
                "canais": {
                    "mercadolivre": {"ativo": True, "preco": 39.9, "estoque": 10, "taxa_canal_pct": 18.0},
                    "shopee": {"ativo": False, "preco": 0, "estoque": 0},
                },
            },
            {
                "sku": "IMP-MIMO-003",
                "nome": "Mimo",
                "prioridade": "P0",
                "fase_atual": 1,
                "custo_total": 40.0,
                "frete_estimado": 9.0,
                "preco": 44.9,
                "vd_dia_ml_ref": 1,
                "canais": {
                    "mercadolivre": {"ativo": True, "preco": 44.9, "estoque": 4, "taxa_canal_pct": 18.0},
                    "shopee": {"ativo": False, "preco": 0, "estoque": 0},
                },
            },
        ]

        def _cotacao(*_a, **_k):
            return {"ok": True, "usd_brl": 5.2, "fonte": "awesomeapi", "confiavel": True, "idade_seg": 0}

        with (
            patch.object(cfg, "CENARIO_MACRO_ATIVO", True),
            patch.object(cfg, "CENARIO_REPOSICAO_ALTA_PCT", 10.0),
            patch.object(cfg, "CENARIO_MARGEM_ADICIONAL_PP", 2.0),
            patch.object(cfg, "CENARIO_CAMBIO_REFERENCIA", 4.95),
            patch.object(cfg, "CENARIO_FRETE_ALTA_PCT", 0.0),
            patch.object(ag, "SNAPSHOT", tmp := __import__("pathlib").Path("/tmp/cenario_macro_teste.json")),
            patch.object(ag, "_skus_importacao_ativos", return_value=[{"id": "pla", "ativo": True, "preco_max_usd": 3.5, "peso_kg": 1, "nome": "PLA"}]),
            patch("core.catalogo_produtos.carregar_produtos_para_operacao", return_value=produtos),
            patch("integracoes.cambio.cotacao_usd.obter_cotacao_usd", side_effect=_cotacao),
            patch("integracoes.cambio.cotacao_usd.cotacao_confiavel_para_margem", return_value=True),
            patch("integracoes.esmaltes.doutrina_guerra_impala.carregar_doutrina", return_value={"preco_congelado": ["IMP-MIMO-003"]}),
            patch.object(ag, "alertar_gestor", return_value=True) as alerta,
            patch.object(ag, "gauge"),
        ):
            out = ag.executar(enviar_alerta=True)

        self.assertTrue(out["ativo"])
        self.assertTrue(tmp.is_file())
        self.assertEqual(out["cambio"]["regime"], "estresse")
        self.assertTrue(any(a["aviso"] == "piso_acima_do_congelado" for a in out["piso_acima_do_congelado"]))
        alerta.assert_called_once()
        tmp.unlink(missing_ok=True)


class AgenteDesligadoTests(unittest.TestCase):
    def test_nao_chama_rede(self):
        from agentes.precificacao.agente_cenario_macro import executar

        def _rede(*_a, **_k):
            raise AssertionError("obter_cotacao_usd não pode ser chamado")

        with (
            patch.object(cfg, "CENARIO_MACRO_ATIVO", False),
            patch("integracoes.cambio.cotacao_usd.obter_cotacao_usd", side_effect=_rede),
        ):
            out = executar(enviar_alerta=False)
        self.assertEqual(out, {"ok": True, "ativo": False})


if __name__ == "__main__":
    unittest.main()
