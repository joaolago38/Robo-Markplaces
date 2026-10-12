"""
tests/test_agente_monitor_sumare_leiloes.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.leilao import agente_monitor_sumare_leiloes as ag


class AgenteMonitorSumareTests(unittest.TestCase):
    def test_montar_alerta_novo_lote(self):
        novos = [
            {
                "numero_lote": "0009",
                "titulo": "FIAT/UNO MILLE ECONOMY, 11/12",
                "tipo_comitente": "prefeitura",
                "comitente": "PREFEITURA - RIBEIRÃO DO SUL",
                "lance_brl": 5500.0,
                "cidade": "Ribeirão do Sul",
                "uf": "SP",
                "data_fechamento": "15/07/2026",
                "url": "https://www.sumareleiloes.com.br/lotes/abc",
            }
        ]
        msg = ag._montar_alerta(novos, [], {"leiloes_encontrados": 1, "lotes_veiculo_documento": 1, "lance_minimo_brl": 2000})
        self.assertIn("Sumaré", msg)
        self.assertIn("5.500", msg)
        self.assertIn("documento", msg.lower())

    @patch.object(ag, "alertar_gestor", return_value=True)
    @patch.object(ag, "varredura_sumare")
    @patch.object(ag, "_carregar_config")
    def test_executar_com_novos(self, mock_cfg, mock_varredura, _mock_alertar):
        mock_cfg.return_value = {"ativo": True, "lance_minimo_brl": 2000, "alertar_mudanca_lance": True}
        mock_varredura.return_value = {
            "leiloes_encontrados": 1,
            "lotes": [
                {
                    "hash": "abc123",
                    "numero_lote": "1",
                    "titulo": "FIAT/UNO",
                    "lance_brl": 3000.0,
                    "url": "https://x",
                    "tipo_comitente": "prefeitura",
                    "comitente": "PREFEITURA",
                }
            ],
        }
        with patch.object(ag, "ler_json", return_value={"lotes": {}}):
            with patch.object(ag, "escrever_json_atomico"):
                out = ag.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["novos"]), 1)


if __name__ == "__main__":
    unittest.main()
