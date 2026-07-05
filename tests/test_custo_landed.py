"""
tests/test_custo_landed.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.importacao import custo_landed as cl


class CustoLandedTests(unittest.TestCase):
    def test_maritimo_menor_que_aereo(self):
        cenarios = cl.calcular_cenarios_frete(
            4.0,
            cambio_usd_brl=5.5,
            peso_kg_unit=1.0,
            quantidade=100,
        )
        self.assertTrue(cenarios["maritimo"]["ok"])
        self.assertTrue(cenarios["aereo"]["ok"])
        self.assertLess(
            cenarios["maritimo"]["custo_unitario_brl"],
            cenarios["aereo"]["custo_unitario_brl"],
        )
        self.assertEqual(cenarios["melhor_frete"], "maritimo")

    def test_impostos_inclusos(self):
        out = cl.calcular_custo_landed(3.0, cambio_usd_brl=5.0, quantidade=50, modo_frete="maritimo")
        self.assertTrue(out["ok"])
        self.assertGreater(out["ii_brl"], 0)
        self.assertGreater(out["pis_brl"], 0)
        self.assertGreater(out["cofins_brl"], 0)
        self.assertGreater(out["icms_brl"], 0)
        self.assertGreater(out["custo_unitario_brl"], out["fob_usd_unit"] * 5.0)

    def test_margem_lucro_razoavel(self):
        m = cl.calcular_margem_revenda(80.0, 40.0, taxa_marketplace_pct=14.0, margem_minima_pct=18.0)
        self.assertTrue(m["ok"])
        self.assertTrue(m["lucro_razoavel"])
        self.assertGreater(m["margem_pct"], 18)

    def test_margem_baixa_nao_lucrativa(self):
        m = cl.calcular_margem_revenda(50.0, 48.0, margem_minima_pct=18.0)
        self.assertTrue(m["ok"])
        self.assertFalse(m["lucro_razoavel"])


if __name__ == "__main__":
    unittest.main()
