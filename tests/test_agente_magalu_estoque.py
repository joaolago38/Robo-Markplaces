"""
tests/test_agente_magalu_estoque.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.magalu import agente_magalu


class TestAgenteMagaluEstoque(unittest.TestCase):
    def test_validar_produto_estoque_none(self):
        self.assertFalse(agente_magalu.validar_produto({"sku": "A", "estoque": None}))

    def test_validar_produto_com_estoque(self):
        self.assertTrue(agente_magalu.validar_produto({"sku": "A", "estoque": 5}))


if __name__ == "__main__":
    unittest.main()
