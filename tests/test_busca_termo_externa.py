"""
tests/test_busca_termo_externa.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.marketplaces import busca_termo_externa as mod


class BuscaTermoExternaTests(unittest.TestCase):
    @patch.object(mod, "_buscar_brave_site", return_value=[])
    @patch.object(mod, "_buscar_ddg_site")
    def test_buscar_por_termo_magalu_normaliza_hit(self, mock_ddg, _mock_brave):
        mock_ddg.return_value = [
            {
                "url": "https://www.magazineluiza.com.br/removedor-esmalte/p/abc",
                "titulo": "Removedor Acetona Cruzeiro 500ml - R$ 28,90",
                "snippet": "Frete grátis",
            }
        ]
        out = mod.buscar_por_termo("magalu", "acetona cruzeiro", limite=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["marketplace"], "magalu")
        self.assertEqual(out[0]["preco"], 28.90)
        self.assertTrue(out[0]["frete_gratis"])
        self.assertTrue(out[0]["item_id"].startswith("MAGALU-"))

    def test_marketplace_invalido_retorna_vazio(self):
        self.assertEqual(mod.buscar_por_termo("ebay", "x"), [])

    def test_termo_vazio_retorna_vazio(self):
        self.assertEqual(mod.buscar_por_termo("shopee", ""), [])

    def test_parse_preco(self):
        self.assertEqual(mod._parse_preco("Produto R$ 1.299,99"), 1299.99)
        self.assertEqual(mod._parse_preco("sem preço"), 0.0)


if __name__ == "__main__":
    unittest.main()
