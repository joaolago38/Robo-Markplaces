"""
tests/test_agente_monitor_carros_batidos.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.veiculos import agente_monitor_carros_batidos as agente


class TestAgenteMonitorCarrosBatidos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "carregar_fontes")
    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "coletar_fonte")
    def test_alerta_novos_anuncios(self, mock_coleta, mock_alerta, mock_fontes):
        with patch.object(agente, "CARROS_BATIDOS_ALERTA_RESUMO", False), patch.object(
            agente, "CARROS_BATIDOS_INCLUIR_FIPE", False
        ), patch.object(agente, "CARROS_BATIDOS_BUSCA_WEB", False):
            mock_fontes.return_value = [{"id": "teste", "nome": "Loja Teste", "tipo": "html"}]
            mock_coleta.return_value = [
                {
                    "hash": "h1",
                    "titulo": "Gol 1.0 2012",
                    "loja_nome": "Loja Teste",
                    "preco": 12000.0,
                    "url": "http://x",
                    "ano": "2012",
                }
            ]
            with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
                agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"
            ):
                out1 = agente.executar(enviar_alerta=True)
                out2 = agente.executar(enviar_alerta=True)
            self.assertTrue(out1["ok"])
            self.assertEqual(out1["novos"], 1)
            self.assertEqual(out2["novos"], 0)
            mock_alerta.assert_called_once()
            self.assertIn("Carros batidos", mock_alerta.call_args[0][0])

    @patch.object(agente, "carregar_fontes", return_value=[])
    def test_sem_fontes_ativas(self, _mock_fontes):
        out = agente.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["lojas"], 0)

    @patch.object(agente, "carregar_fontes")
    @patch.object(agente, "coletar_fonte", side_effect=RuntimeError("boom"))
    def test_nunca_lanca_excecao(self, _mock_coleta, mock_fontes):
        mock_fontes.return_value = [{"id": "x", "nome": "X", "tipo": "html"}]
        out = agente.executar(enviar_alerta=False)
        self.assertFalse(out["ok"])
        self.assertIn("boom", out["erro"])

    def test_montar_alerta_novos(self):
        msg = agente._montar_alerta_novos(
            [{"titulo": "Civic 2016", "loja_nome": "Motorjan", "preco": 25000, "url": "http://x", "ano": "2016"}]
        )
        self.assertIn("Civic", msg)
        self.assertIn("Motorjan", msg)


if __name__ == "__main__":
    unittest.main()
