"""tests/test_comparar_portos_alibaba.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.importacao import comparar_portos_alibaba as cmp
from integracoes.importacao import portos_brasil as pb


class TestPortosBrasil(unittest.TestCase):
    def test_lista_aereo_e_maritimo(self):
        aeros = pb.listar_gateways(modal="aereo")
        portos = pb.listar_gateways(modal="maritimo")
        self.assertGreaterEqual(len(aeros), 8)
        self.assertGreaterEqual(len(portos), 10)
        self.assertTrue(any(g["codigo"] == "VCP" for g in aeros))
        self.assertTrue(any(g["codigo"] == "BRSSZ" for g in portos))

    def test_gateway_santos(self):
        g = pb.gateway_por_codigo("BRSSZ")
        self.assertIsNotNone(g)
        self.assertEqual(g["tipo"], "maritimo")
        self.assertIn("custos_locais_brl", g)

    def test_distancia_cep_padrao(self):
        km = pb.distancia_km_para_cep("VCP", "13467-694")
        self.assertEqual(km, 120.0)


class TestCompararPortos(unittest.TestCase):
    def test_normalizar_produto(self):
        n = cmp.normalizar_produto_alibaba(
            {"nome": "PLA", "preco_usd": 10.0, "unidade_por_preco": 2, "peso_kg": 1, "termo_busca": "x"}
        )
        self.assertEqual(n["preco_fob_usd"], 5.0)
        self.assertEqual(n["origem"], "alibaba")

    def test_comparar_ranqueia_atrativos(self):
        with patch(
            "integracoes.cambio.cotacao_usd.obter_cotacao_usd",
            return_value={"ok": True, "usd_brl": 5.5, "fonte": "teste", "confiavel": True},
        ), patch(
            "integracoes.cambio.cotacao_usd.cotacao_confiavel_para_margem",
            return_value=True,
        ), patch("integracoes.importacao.comparar_portos_alibaba.escrever_json_atomico"), patch(
            "integracoes.importacao.comparar_portos_alibaba.gauge"
        ), patch("integracoes.importacao.comparar_portos_alibaba.incrementar"):
            out = cmp.comparar_portos_para_produto_alibaba(
                {
                    "nome": "Filamento PLA",
                    "preco_fob_usd": 2.0,
                    "peso_kg": 1.0,
                    "moq": 100,
                    "ii_pct": 12.6,
                    "termo_busca": "PLA filament",
                },
                cambio_usd_brl=5.5,
                cep_destino="13467-694",
                modal="todos",
                top_n=5,
            )
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["total_gateways_avaliados"], 15)
        self.assertIsNotNone(out["melhor_geral"])
        self.assertIsNotNone(out["melhor_aereo"])
        self.assertIsNotNone(out["melhor_maritimo"])
        self.assertEqual(out["referencia"], "alibaba")
        # Marítimo em geral mais barato unitário em volume
        self.assertIn(out["melhor_maritimo"]["modal"], ("maritimo",))
        msg = cmp.formatar_comparacao_telegram(out)
        self.assertIn("Alibaba", msg)
        self.assertIn("Marítimo", msg)

    def test_landed_gateway_vcp(self):
        g = pb.gateway_por_codigo("VCP")
        assert g is not None
        prod = cmp.normalizar_produto_alibaba(
            {"preco_fob_usd": 3.0, "peso_kg": 1.0, "moq": 50, "termo_busca": "x"}
        )
        cen = cmp.calcular_landed_no_gateway(
            prod, g, cambio_usd_brl=5.0, cep_destino="13467-694", uf_destino="SP"
        )
        self.assertTrue(cen["ok"])
        self.assertEqual(cen["modal"], "aereo")
        self.assertGreater(cen["custo_unitario_brl"], 0)
        self.assertGreater(cen["score_atratividade"], 0)
        self.assertTrue(cen["custos_considerados"])
        self.assertTrue(cen["detalhe_custos"]["completo"])
        self.assertIn("frete_internacional_brl", cen["detalhe_custos"]["blocos"])
        self.assertIn("impostos_brl", cen["detalhe_custos"]["blocos"])
        self.assertIn("custos_locais_brl", cen["detalhe_custos"]["blocos"])
        self.assertIsNotNone(cen["assertividade_pct"])

    def test_abaixo_90_exige_custo(self):
        """Assertividade < 90% → não entra em atrativos de alta confiança sem custo completo."""
        g = pb.gateway_por_codigo("BRMAO")
        assert g is not None
        prod = cmp.normalizar_produto_alibaba(
            {"preco_fob_usd": 0.5, "peso_kg": 5.0, "moq": 10, "termo_busca": "x", "ii_pct": 20}
        )
        cen = cmp.calcular_landed_no_gateway(
            prod, g, cambio_usd_brl=5.5, cep_destino="13467-694", uf_destino="SP"
        )
        self.assertTrue(cen["ok"])
        self.assertTrue(cen["custos_considerados"])
        # Se assertividade < 90, exige_revisao_custo e não é atrativa "alta"
        if cen["assertividade_pct"] < 90:
            self.assertTrue(cen["exige_revisao_custo"])
            self.assertFalse(cmp.eh_condicao_atrativa(cen))
            self.assertTrue(cmp.eh_condicao_atrativa_condicional(cen) or cen["score_atratividade"] < 55)

    def test_sem_detalhe_custo_cap_assertividade(self):
        score = cmp._score_atratividade(
            landed_unit=20.0,
            fob_usd=5.0,
            cambio=5.0,
            atratividade_cat=98.0,
            modal="maritimo",
            detalhe_custos={"completo": False, "coerente": False},
        )
        self.assertLess(score, 90.0)

    def test_comparar_expone_condicionais(self):
        with patch(
            "integracoes.cambio.cotacao_usd.obter_cotacao_usd",
            return_value={"ok": True, "usd_brl": 5.5, "fonte": "teste", "confiavel": True},
        ), patch(
            "integracoes.cambio.cotacao_usd.cotacao_confiavel_para_margem",
            return_value=True,
        ), patch("integracoes.importacao.comparar_portos_alibaba.escrever_json_atomico"), patch(
            "integracoes.importacao.comparar_portos_alibaba.gauge"
        ), patch("integracoes.importacao.comparar_portos_alibaba.incrementar"):
            out = cmp.comparar_portos_para_produto_alibaba(
                {
                    "nome": "Item teste",
                    "preco_fob_usd": 2.0,
                    "peso_kg": 1.0,
                    "moq": 100,
                    "termo_busca": "x",
                },
                cambio_usd_brl=5.5,
                cep_destino="13467-694",
            )
        self.assertEqual(out["assertividade_alvo_pct"], 90.0)
        self.assertIn("total_condicionais_custo", out)
        melhor = out.get("melhor_geral") or {}
        if melhor:
            self.assertIn("assertividade_pct", melhor)
            self.assertTrue(melhor.get("custos_considerados"))


if __name__ == "__main__":
    unittest.main()
