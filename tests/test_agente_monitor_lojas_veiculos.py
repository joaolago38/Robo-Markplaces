"""
tests/test_agente_monitor_lojas_veiculos.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.veiculos import agente_monitor_lojas_veiculos as agente


class AgenteMonitorLojasVeiculosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "FONTES_PADRAO", ({"id": "teste", "nome": "Teste", "tipo": "html"},))
    @patch.object(agente, "LOJAS_VEICULOS_ALERTA_RESUMO", False)
    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "coletar_fonte")
    @patch.object(agente, "filtrar_oportunidades")
    def test_alerta_apenas_novos(self, mock_filtro, mock_coleta, mock_alerta, _fontes):
        mock_coleta.return_value = [{"hash": "h1", "preco": 10000}]
        mock_filtro.return_value = [
            {
                "hash": "h1",
                "titulo": "Gol 1.0",
                "loja_nome": "Leopardo",
                "preco": 10000,
                "valor_fipe": 20000,
                "desconto_pct": 50,
                "margem_reais": 10000,
                "url": "http://x",
            }
        ]
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"):
            out1 = agente.executar(enviar_alerta=True)
            out2 = agente.executar(enviar_alerta=True)
        self.assertTrue(out1["ok"])
        self.assertEqual(out1["novos"], 1)
        self.assertEqual(out2["novos"], 0)
        self.assertEqual(mock_alerta.call_count, 1)

    @patch.object(agente, "coletar_fonte", side_effect=RuntimeError("boom"))
    def test_nunca_lanca_excecao(self, _mock):
        out = agente.executar(enviar_alerta=False)
        self.assertFalse(out["ok"])
        self.assertIn("boom", out.get("erro", ""))


if __name__ == "__main__":
    unittest.main()
