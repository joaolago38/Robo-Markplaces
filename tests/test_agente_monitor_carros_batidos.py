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
        with patch.object(agente, "CARROS_BATIDOS_BUSCA_WEB", False):
            out = agente.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["lojas"], 0)

    @patch.object(agente, "carregar_fontes", return_value=[])
    @patch.object(agente, "coletar_busca_web_brasil")
    def test_busca_web_gera_lojas(self, mock_busca_web, _mock_fontes):
        mock_busca_web.return_value = [
            {
                "hash": "w1",
                "titulo": "Loja de batidos SP",
                "loja_nome": "Busca web — exemplo.com.br",
                "loja_id": "busca_web",
                "preco": 0.0,
                "url": "https://exemplo.com.br",
                "ano": "",
            }
        ]
        with patch.object(agente, "CARROS_BATIDOS_BUSCA_WEB", True), patch.object(
            agente, "CARROS_BATIDOS_ALERTA_RESUMO", False
        ), patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"
        ):
            out = agente.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["lojas"], 1)
        self.assertEqual(out["novos"], 1)
        mock_busca_web.assert_called_once()

    @patch.object(agente, "carregar_fontes")
    @patch.object(agente, "coletar_fonte", side_effect=RuntimeError("boom"))
    def test_nunca_lanca_excecao(self, _mock_coleta, mock_fontes):
        mock_fontes.return_value = [{"id": "x", "nome": "X", "tipo": "html"}]
        with patch.object(agente, "CARROS_BATIDOS_BUSCA_WEB", False):
            out = agente.executar(enviar_alerta=False)
        self.assertFalse(out["ok"])
        self.assertIn("boom", out["erro"])

    def test_montar_alerta_novos(self):
        msg = agente._montar_alerta_novos(
            [{"titulo": "Civic 2016", "loja_nome": "Motorjan", "preco": 25000, "url": "http://x", "ano": "2016"}]
        )
        self.assertIn("Civic", msg)
        self.assertIn("Motorjan", msg)
        self.assertIn("Top", msg)

    def test_ordenar_novos_prioriza_desconto(self):
        itens = [
            {"titulo": "A", "preco": 10000, "desconto_pct": 10},
            {"titulo": "B", "preco": 8000, "desconto_pct": 40},
            {"titulo": "C", "preco": 0, "desconto_pct": 99},
        ]
        out = agente._ordenar_novos_alerta(itens)
        self.assertEqual(out[0]["titulo"], "B")
        self.assertEqual(out[-1]["titulo"], "C")

    def test_filtrar_preco_ignorar(self):
        caros = [{"preco": 219900.0, "titulo": "Titano"}]
        with patch.object(agente, "CARROS_BATIDOS_PRECO_MAX", 150000.0):
            self.assertEqual(agente._filtrar_preco(caros), [])
            self.assertEqual(len(agente._filtrar_preco(caros, ignorar=True)), 1)

    @patch.object(agente, "carregar_fontes")
    @patch.object(agente, "coletar_fonte")
    def test_ignorar_preco_max_no_catalogo(self, mock_coleta, mock_fontes):
        mock_fontes.return_value = [
            {
                "id": "esperanca_batidos",
                "nome": "Esperança Batidos",
                "tipo": "esperanca",
                "ignorar_preco_max": True,
            }
        ]
        mock_coleta.return_value = [
            {
                "hash": "e1",
                "titulo": "Fiat Titano",
                "loja_nome": "Esperança Batidos",
                "preco": 219900.0,
                "url": "http://x",
                "ano": "2025",
            }
        ]
        with patch.object(agente, "CARROS_BATIDOS_PRECO_MAX", 150000.0), patch.object(
            agente, "CARROS_BATIDOS_BUSCA_WEB", False
        ), patch.object(agente, "CARROS_BATIDOS_INCLUIR_FIPE", False), patch.object(
            agente, "CARROS_BATIDOS_ALERTA_RESUMO", False
        ), patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"
        ):
            out = agente.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["resultados"][0]["total"], 1)


if __name__ == "__main__":
    unittest.main()
