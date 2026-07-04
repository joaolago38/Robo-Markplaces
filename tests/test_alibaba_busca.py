"""
tests/test_alibaba_busca.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.alibaba import busca


class TestAlibabaBuscaHelpers(unittest.TestCase):
    def test_montar_termo_prioriza_termo_busca(self):
        t = busca.montar_termo_busca({"termo_busca": "nail polish bottle", "nome": "X"})
        self.assertEqual(t, "nail polish bottle")

    def test_extrair_preco_usd(self):
        self.assertAlmostEqual(busca._extrair_preco_usd("from US $0.28 / piece"), 0.28)

    def test_extrair_moq(self):
        self.assertEqual(busca._extrair_moq("MOQ: 500 pieces"), 500)

    def test_e_oportunidade_respeita_preco_max(self):
        produto = {"preco_max_usd": 0.5}
        self.assertTrue(busca._e_oportunidade(produto, {"preco_usd": 0.3, "url": "http://x"}))
        self.assertFalse(busca._e_oportunidade(produto, {"preco_usd": 0.9, "url": "http://x"}))


class TestBuscarOportunidades(unittest.TestCase):
    @patch.object(busca, "buscar_duckduckgo", return_value=[])
    @patch.object(busca, "buscar_alibaba_direto")
    def test_retorna_novos_itens(self, mock_direto, _ddg):
        mock_direto.return_value = [
            {
                "url": "https://www.alibaba.com/product-detail/123.html",
                "titulo": "nail polish bottle wholesale",
                "snippet": "Trade Assurance MOQ 100",
                "preco_usd": 0.25,
                "moq": 100,
                "fonte": "alibaba_search",
            }
        ]
        produto = {
            "termo_busca": "nail polish bottle",
            "preco_max_usd": 0.5,
            "moq_max": 5000,
        }
        out = busca.buscar_oportunidades(produto, pausa_seg=0)
        self.assertEqual(len(out), 1)
        self.assertIn("alibaba.com", out[0]["url"])


if __name__ == "__main__":
    unittest.main()
