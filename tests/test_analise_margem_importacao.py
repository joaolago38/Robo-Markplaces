"""
tests/test_analise_margem_importacao.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.importacao import analise_margem as am


class AnaliseMargemTests(unittest.TestCase):
    @patch("integracoes.ml.ml_client.buscar_concorrentes_por_termo")
    def test_consultar_precos_marketplace(self, mock_ml):
        mock_ml.return_value = [
            {"preco": 60.0, "titulo": "A"},
            {"preco": 80.0, "titulo": "B"},
            {"preco": 70.0, "titulo": "C"},
        ]
        out = am.consultar_precos_marketplace("filamento pla")
        self.assertTrue(out["ok"])
        self.assertEqual(out["preco_min_brl"], 60.0)
        self.assertEqual(out["preco_mediana_brl"], 70.0)

    @patch("integracoes.importacao.analise_margem.consultar_precos_marketplace")
    def test_analisar_produto_catalogo(self, mock_mk):
        mock_mk.return_value = {
            "ok": True,
            "preco_mediana_brl": 75.0,
            "preco_min_brl": 60.0,
            "total_anuncios": 5,
        }
        produto = {
            "id": "p1",
            "nome": "Filamento PLA",
            "peso_kg": 1,
            "termo_marketplace": "filamento pla",
            "margem_minima_pct": 10,
            "margem_minima_reais": 3,
        }
        oportunidades = [
            {
                "titulo": "PLA 1kg",
                "preco_usd": 3.5,
                "moq": 100,
                "url": "https://www.alibaba.com/x.html",
            }
        ]
        out = am.analisar_produto_catalogo(produto, oportunidades, cambio_usd_brl=5.5)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_oportunidades"], 1)
        self.assertIsNotNone(out["melhor_analise"])


if __name__ == "__main__":
    unittest.main()
