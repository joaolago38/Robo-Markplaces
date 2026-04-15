import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.marketplace_algorithm import avaliar_marketplace


class MarketplaceAlgorithmTests(unittest.TestCase):
    def test_marketplace_nao_configurado_vira_critico(self):
        out = avaliar_marketplace(
            "market_x_test",
            {"configurado": False, "pendencias": 0, "claims_rate": 0.0, "dias_sem_acesso": 0},
        )
        self.assertEqual(out["score"], 0)
        self.assertEqual(out["status"], "critico")

    def test_marketplace_saudavel(self):
        out = avaliar_marketplace(
            "market_ok_test",
            {"configurado": True, "pendencias": 1, "claims_rate": 0.0, "dias_sem_acesso": 0},
        )
        self.assertGreaterEqual(out["score"], 80)
        self.assertEqual(out["status"], "saudavel")

    def test_marketplace_atencao_com_pendencias(self):
        out = avaliar_marketplace(
            "market_mid_test",
            {"configurado": True, "pendencias": 20, "claims_rate": 0.0, "dias_sem_acesso": 3},
        )
        self.assertTrue(60 <= out["score"] < 80)
        self.assertEqual(out["status"], "atencao")


if __name__ == "__main__":
    unittest.main()
