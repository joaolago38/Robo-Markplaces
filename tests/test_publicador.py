"""
tests/test_publicador.py — estoque None não quebra selecionar_produto.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.social import publicador


class TestPublicador(unittest.TestCase):
    @patch("agentes.social.publicador.listar_produtos")
    def test_estoque_none_tratado_como_zero(self, mock_listar):
        mock_listar.return_value = [
            {"sku": "A", "estoque": None, "preco": 10, "custo": 5},
            {"sku": "B", "estoque": 50, "preco": 20, "custo": 8},
        ]
        with patch.object(publicador, "ESTOQUE_CRITICO", 10):
            produto = publicador.selecionar_produto()
        self.assertIsNotNone(produto)
        self.assertEqual(produto["sku"], "B")

    @patch("agentes.social.publicador.listar_produtos", return_value=[{"sku": "X", "estoque": None}])
    def test_somente_none_retorna_none(self, *_):
        with patch.object(publicador, "ESTOQUE_CRITICO", 10):
            self.assertIsNone(publicador.selecionar_produto())


if __name__ == "__main__":
    unittest.main()
