"""
tests/test_algoritmo_marketplaces.py — ALG01–ALG03
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes import algoritmo_marketplaces as algo


def _av_saudavel():
    return {"status": "saudavel", "score": 90, "acoes_recomendadas": [], "variacoes_relevantes": []}


class TestAlgoritmoMarketplaces(unittest.TestCase):
    @patch.object(algo, "alertar_gestor")
    @patch.object(algo, "avaliar_marketplace", return_value=_av_saudavel())
    @patch.object(algo, "saude_amazon", return_value={})
    @patch.object(algo, "saude_magalu", return_value={})
    @patch.object(algo, "saude_shopee", return_value={})
    @patch.object(algo, "saude_ml", return_value={})
    def test_ALG01_executar_resumo_quatro_saudaveis(self, *_mocks):
        out = algo.executar()
        self.assertIn("resumo", out)
        self.assertIn("marketplaces", out)
        self.assertEqual(out["resumo"]["saudavel"], 4)

    @patch.object(algo, "alertar_gestor")
    @patch.object(algo, "avaliar_marketplace")
    @patch.object(algo, "saude_amazon", return_value={})
    @patch.object(algo, "saude_magalu", return_value={})
    @patch.object(algo, "saude_shopee", return_value={})
    @patch.object(algo, "saude_ml", return_value={})
    def test_ALG02_executar_alerta_critico(self, _ml, _sh, _mg, _am, mock_aval, mock_alert):
        def side(nome, _metrics):
            if nome == "mercadolivre":
                return {
                    "status": "critico",
                    "score": 10,
                    "acoes_recomendadas": ["revisar"],
                    "variacoes_relevantes": [],
                }
            return _av_saudavel()

        mock_aval.side_effect = side
        algo.executar(alertar_quando_atencao=False)
        mock_alert.assert_called()

    @patch.object(algo, "alertar_gestor")
    @patch.object(algo, "avaliar_marketplace")
    @patch.object(algo, "saude_amazon", return_value={})
    @patch.object(algo, "saude_magalu", return_value={})
    @patch.object(algo, "saude_shopee", return_value={})
    @patch.object(algo, "saude_ml", return_value={})
    def test_ALG03_executar_contagem_status(self, _ml, _sh, _mg, _am, mock_aval, _mock_alert):
        mock_aval.side_effect = [
            {"status": "saudavel", "score": 90, "acoes_recomendadas": [], "variacoes_relevantes": []},
            {"status": "saudavel", "score": 90, "acoes_recomendadas": [], "variacoes_relevantes": []},
            {"status": "atencao", "score": 60, "acoes_recomendadas": [], "variacoes_relevantes": []},
            {"status": "critico", "score": 20, "acoes_recomendadas": [], "variacoes_relevantes": []},
        ]
        out = algo.executar()
        self.assertEqual(out["resumo"]["saudavel"], 2)
        self.assertEqual(out["resumo"]["atencao"], 1)
        self.assertEqual(out["resumo"]["critico"], 1)


if __name__ == "__main__":
    unittest.main()
