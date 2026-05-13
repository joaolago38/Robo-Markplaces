"""
tests/test_fiscal_mapper.py — FM01–FM09
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import fiscal_mapper


class TestFiscalMapperValidacao(unittest.TestCase):
    def test_FM01_ncm_valido_8_digitos(self):
        self.assertTrue(fiscal_mapper.ncm_valido("33041000"))
        self.assertTrue(fiscal_mapper.ncm_valido("3304.10.00"))

    def test_FM02_ncm_valido_invalidos(self):
        self.assertFalse(fiscal_mapper.ncm_valido(""))
        self.assertFalse(fiscal_mapper.ncm_valido("1234"))
        self.assertFalse(fiscal_mapper.ncm_valido("123456789"))
        self.assertFalse(fiscal_mapper.ncm_valido("ABCD1234"))


class TestFiscalMapperBusca(unittest.TestCase):
    @patch.object(fiscal_mapper, "_carregar_catalogo", return_value=[{"sku": "IMP-MIMO-003", "ncm": "33041000"}])
    def test_FM03_buscar_ncm_por_sku_encontrado(self, _mock_cat):
        self.assertEqual(fiscal_mapper.buscar_ncm_por_sku("IMP-MIMO-003"), "33041000")

    @patch.object(fiscal_mapper, "_carregar_catalogo", return_value=[])
    def test_FM04_buscar_ncm_por_sku_inexistente(self, _mock_cat):
        self.assertIsNone(fiscal_mapper.buscar_ncm_por_sku("SKU-INEXISTENTE"))

    @patch.object(fiscal_mapper, "_carregar_catalogo", return_value=[{"sku": "imp-mimo-003", "ncm": "33041000"}])
    def test_FM05_buscar_ncm_por_sku_case_insensitive(self, _mock_cat):
        self.assertEqual(fiscal_mapper.buscar_ncm_por_sku("IMP-MIMO-003"), "33041000")


class TestFiscalMapperResolver(unittest.TestCase):
    def test_FM06_resolver_ncm_item_prioridade_item(self):
        item = {"sku": "X", "ncm": "33041000"}
        with patch.object(fiscal_mapper, "buscar_ncm_por_sku") as mock_busca:
            out = fiscal_mapper.resolver_ncm_item(item)
        self.assertEqual(out, "33041000")
        mock_busca.assert_not_called()

    def test_FM07_resolver_ncm_item_prioridade_bling(self):
        item = {"sku": "X", "ncm": ""}
        produto_bling = {"ncm": "33041000"}
        with patch.object(fiscal_mapper, "buscar_ncm_por_sku") as mock_busca:
            out = fiscal_mapper.resolver_ncm_item(item, produto_bling)
        self.assertEqual(out, "33041000")
        mock_busca.assert_not_called()

    def test_FM08_resolver_ncm_item_fallback_catalogo(self):
        item = {"sku": "IMP-MIMO-003", "ncm": ""}
        produto_bling = {"ncm": ""}
        with patch.object(fiscal_mapper, "buscar_ncm_por_sku", return_value="33041000") as mock_busca:
            out = fiscal_mapper.resolver_ncm_item(item, produto_bling)
        self.assertEqual(out, "33041000")
        mock_busca.assert_called_once()

    def test_FM09_resolver_ncm_item_sem_fonte_valida(self):
        item = {"sku": "SKU-SEM-NCM", "ncm": ""}
        self.assertIsNone(fiscal_mapper.resolver_ncm_item(item, None))


if __name__ == "__main__":
    unittest.main()
