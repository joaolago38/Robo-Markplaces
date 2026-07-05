"""
tests/test_veiculos_fipe_comparacao.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.veiculos import comparacao as cmp
from integracoes.veiculos import fipe_client as fipe


class FipeComparacaoTests(unittest.TestCase):
    def test_parse_valor_fipe(self):
        self.assertEqual(fipe.parse_valor_fipe("R$ 32.500,00"), 32500.0)

    def test_calcular_margem(self):
        m = cmp.calcular_margem_fipe(preco_anunciado=10000, valor_fipe=20000)
        self.assertEqual(m["desconto_pct"], 50.0)
        self.assertEqual(m["margem_reais"], 10000.0)

    @patch("integracoes.veiculos.comparacao.consultar_preco_fipe")
    def test_avaliar_anuncio_oportunidade(self, mock_fipe):
        mock_fipe.return_value = {
            "valor_fipe": 20000.0,
            "marca_fipe": "Fiat",
            "modelo_fipe": "Uno",
            "ano_fipe": 2012,
        }
        anuncio = {
            "hash": "abc",
            "titulo": "Uno Mille",
            "marca": "Fiat",
            "ano": "2011/2012",
            "preco": 12000.0,
            "url": "http://x",
        }
        out = cmp.avaliar_anuncio(anuncio, preco_max=20000, margem_min_pct=25)
        self.assertTrue(out)
        self.assertGreaterEqual(out["desconto_pct"], 25)

    @patch("integracoes.veiculos.comparacao.consultar_preco_fipe")
    def test_avaliar_rejeita_preco_alto(self, mock_fipe):
        mock_fipe.return_value = {"valor_fipe": 50000.0}
        out = cmp.avaliar_anuncio(
            {"preco": 25000, "marca": "X", "titulo": "Y", "ano": "2010"},
            preco_max=20000,
            margem_min_pct=10,
        )
        self.assertIsNone(out)
        mock_fipe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
