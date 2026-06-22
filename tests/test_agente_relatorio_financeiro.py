"""
tests/test_agente_relatorio_financeiro.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agentes.relatorio_financeiro as rel


class TestRelatorioFinanceiro(unittest.TestCase):
    @patch.object(rel, "alertar_gestor", return_value=True)
    @patch("agentes.ml.agente_monitor_ml.analisar")
    @patch("agentes.repricing.agente_repricing_marketplaces.executar")
    def test_sucesso_com_numeros_positivos(self, mock_repricing, mock_monitor, mock_alerta):
        mock_repricing.return_value = {
            "economia_estimada_piso_margem": 12.5,
            "total_ajustes": 3,
        }
        mock_monitor.return_value = {
            "ok": True,
            "ads": {
                "campanhas_acos_alto": [{"cost": 30.0}, {"cost": 15.0}],
            },
        }
        self.assertTrue(rel.executar())
        mock_alerta.assert_called_once()
        msg = mock_alerta.call_args[0][0]
        self.assertIn("R$12.50", msg)
        self.assertIn("3 ajustes", msg)

    @patch.object(rel, "alertar_gestor", return_value=True)
    @patch("agentes.ml.agente_monitor_ml.analisar")
    @patch("agentes.repricing.agente_repricing_marketplaces.executar")
    def test_sem_ajustes_ainda_envia(self, mock_repricing, mock_monitor, mock_alerta):
        mock_repricing.return_value = {
            "economia_estimada_piso_margem": 0.0,
            "total_ajustes": 0,
        }
        mock_monitor.return_value = {"ok": True, "ads": {"campanhas_acos_alto": []}}
        self.assertTrue(rel.executar())
        mock_alerta.assert_called_once()

    @patch.object(rel, "alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.executar", side_effect=RuntimeError("falha"))
    def test_excecao_retorna_false(self, *_mocks):
        self.assertFalse(rel.executar())


if __name__ == "__main__":
    unittest.main()
