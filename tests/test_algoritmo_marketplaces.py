"""
tests/test_algoritmo_marketplaces.py — ALG01–ALG04
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes import algoritmo_marketplaces as algo


def _av_saudavel():
    return {
        "status": "saudavel",
        "score": 90,
        "acoes_recomendadas": [],
        "variacoes_relevantes": [],
        "metrics": {"configurado": True},
    }


def _av_inativo():
    return {
        "status": "inativo",
        "score": 0,
        "acoes_recomendadas": ["canal inativo"],
        "variacoes_relevantes": [],
        "metrics": {"configurado": False},
    }


class TestAlgoritmoMarketplaces(unittest.TestCase):
    @patch.object(algo, "alertar_gestor")
    @patch.object(algo, "avaliar_marketplace", return_value=_av_saudavel())
    @patch.object(algo, "saude_ml", return_value={"configurado": True})
    @patch.object(algo, "_MARKETPLACES_ATIVOS", {"mercadolivre"})
    def test_ALG01_somente_ativos_no_spec(self, *_mocks):
        out = algo.executar()
        self.assertEqual(out["resumo"]["saudavel"], 1)
        self.assertEqual(set(out["marketplaces"]), {"mercadolivre"})
        self.assertNotIn("shopee", out["marketplaces"])
        self.assertNotIn("amazon", out["marketplaces"])

    @patch.object(algo, "alertar_gestor")
    @patch.object(algo, "avaliar_marketplace")
    @patch.object(algo, "saude_ml", return_value={"configurado": True})
    @patch.object(algo, "_MARKETPLACES_ATIVOS", {"mercadolivre"})
    def test_ALG02_executar_alerta_critico(self, _ml, mock_aval, mock_alert):
        mock_aval.return_value = {
            "status": "critico",
            "score": 10,
            "acoes_recomendadas": ["revisar"],
            "variacoes_relevantes": [],
            "metrics": {"configurado": True},
        }
        algo.executar(alertar_quando_atencao=False)
        mock_alert.assert_called()

    @patch.object(algo, "alertar_gestor")
    @patch.object(algo, "avaliar_marketplace")
    @patch.object(algo, "saude_ml", return_value={"configurado": True})
    @patch.object(algo, "saude_shopee", return_value={"configurado": False})
    @patch.object(algo, "_MARKETPLACES_ATIVOS", {"mercadolivre", "shopee"})
    def test_ALG03_executar_contagem_status(self, _sh, _ml, mock_aval, _mock_alert):
        mock_aval.side_effect = [
            {"status": "saudavel", "score": 90, "acoes_recomendadas": [], "variacoes_relevantes": [], "metrics": {"configurado": True}},
            {"status": "critico", "score": 20, "acoes_recomendadas": [], "variacoes_relevantes": [], "metrics": {"configurado": True}},
        ]
        out = algo.executar()
        self.assertEqual(out["resumo"]["saudavel"], 1)
        self.assertEqual(out["resumo"]["atencao"], 0)
        self.assertEqual(out["resumo"]["critico"], 1)

    @patch.object(algo, "alertar_gestor")
    @patch.object(algo, "avaliar_marketplace", return_value=_av_inativo())
    @patch.object(algo, "saude_shopee", return_value={"configurado": False})
    @patch.object(algo, "_MARKETPLACES_ATIVOS", {"shopee"})
    def test_ALG04_inativo_nao_alerta_telegram(self, _sh, _aval, mock_alert):
        out = algo.executar()
        self.assertEqual(out["resumo"]["inativo"], 1)
        self.assertEqual(out["resumo"]["critico"], 0)
        mock_alert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
