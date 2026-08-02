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


if __name__ == "__main__":
    unittest.main()
