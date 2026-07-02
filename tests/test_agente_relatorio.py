"""
tests/test_agente_relatorio.py — RL01–RL03
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes import relatorio


class TestAgenteRelatorio(unittest.TestCase):
    @patch.object(relatorio, "alertar", return_value=True)
    @patch.object(relatorio, "sintetizar_claude", return_value="• Tudo ok")
    @patch.object(relatorio, "estoques_criticos", return_value=[])
    @patch.object(
        relatorio,
        "listar_produtos",
        return_value=[{"nome": "Kit A", "preco": 59.9, "estoque": 50}],
    )
    def test_RL01_executar_alerta_telegram(self, *_patches):
        self.assertTrue(relatorio.executar())
        relatorio.alertar.assert_called_once()

    @patch.object(relatorio, "alertar_critico")
    @patch.object(relatorio, "alertar", return_value=True)
    @patch.object(relatorio, "sintetizar_claude", return_value="ok")
    @patch.object(relatorio, "estoques_criticos", return_value=[{"nome": "Kit B", "estoque": 5}])
    @patch.object(relatorio, "listar_produtos", return_value=[])
    def test_RL02_executar_estoque_critico(self, *_patches):
        relatorio.executar()
        relatorio.alertar_critico.assert_called_once()

    @patch.object(relatorio, "listar_produtos", side_effect=Exception("DB error"))
    def test_RL03_executar_false_em_excecao(self, *_patches):
        self.assertFalse(relatorio.executar())


if __name__ == "__main__":
    unittest.main()
