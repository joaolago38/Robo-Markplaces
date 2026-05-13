"""
tests/test_varredura_marketplaces.py — VAR01–VAR03
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes import agente_varredura_marketplaces as varredura


class TestVarreduraMarketplaces(unittest.TestCase):
    @patch.object(varredura, "listar_shopee")
    @patch.object(varredura, "listar_ml", return_value=[{}, {}, {}])
    def test_VAR01_coletar_respeita_ativos(self, mock_ml, mock_shopee):
        with patch.object(varredura, "_MARKETPLACES_ATIVOS", {"mercadolivre"}):
            out = varredura.coletar_atualizacoes()
        self.assertIn("mercadolivre", out)
        self.assertEqual(out["mercadolivre"], 3)
        self.assertNotIn("shopee", out)
        mock_shopee.assert_not_called()

    @patch.object(varredura, "listar_ml", side_effect=Exception("boom"))
    def test_VAR02_coletar_erro_retorna_zero(self, *_patches):
        with patch.object(varredura, "_MARKETPLACES_ATIVOS", {"mercadolivre"}):
            out = varredura.coletar_atualizacoes()
        self.assertEqual(out["mercadolivre"], 0)

    @patch.object(varredura, "executar_repricing_marketplaces", return_value={})
    @patch.object(varredura, "executar_manutencao_marketplaces", return_value={})
    @patch.object(varredura, "executar_algoritmo_marketplaces", return_value={"resumo": {}})
    @patch.object(varredura, "executar_auto_respostas_visuais", return_value={})
    @patch.object(
        varredura,
        "coletar_atualizacoes",
        return_value={"mercadolivre": 2, "total": 2},
    )
    def test_VAR03_executar_varredura_estrutura(self, *_patches):
        out = varredura.executar_varredura()
        self.assertTrue("timestamp" in out or "atualizacoes" in out)


if __name__ == "__main__":
    unittest.main()
