"""
tests/test_agente_monitor_kits_esmaltes.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.esmaltes import agente_monitor_kits_esmaltes as agente


class AgenteMonitorKitsEsmaltesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "ml_client")
    @patch.object(agente, "_carregar_termos")
    def test_executar_envia_telegram_com_ranking(self, mock_termos, mock_ml, mock_alertar):
        mock_termos.return_value = [
            {
                "id": "impala",
                "ativo": True,
                "nome": "Kits Impala",
                "termo_busca": "esmalte impala kit manicure",
                "limite_resultados": 10,
                "prioridade": 1,
            },
            {
                "id": "anita",
                "ativo": True,
                "nome": "Kits Anita",
                "termo_busca": "esmalte anita kit manicure",
                "limite_resultados": 10,
                "prioridade": 1,
            },
        ]
        mock_ml.buscar_concorrentes_por_termo.side_effect = [
            [
                {
                    "item_id": "MLB1",
                    "titulo": "Kit 10 esmaltes Impala atacado",
                    "preco": 69.0,
                    "quantidade_vendida": 300,
                },
            ],
            [
                {
                    "item_id": "MLB2",
                    "titulo": "Kit 5 esmaltes Anita nude",
                    "preco": 45.0,
                    "quantidade_vendida": 100,
                },
            ],
        ]

        with patch.object(agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"), patch.object(
            agente, "HISTORY_PATH", self.tmp_path / "hist.json"
        ), patch.object(agente, "ESMALTES_KITS_MONITOR_PAUSA_SEG", 0):
            out = agente.executar(enviar_alerta=True)

        self.assertTrue(out["ok"])
        self.assertEqual(out["total_termos"], 2)
        self.assertEqual(out["consolidado"]["total_kits_unicos"], 2)
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("Marcas que mais vendem", msg)
        self.assertIn("Top anúncios", msg)

    def test_montar_mensagem(self):
        msg = agente.montar_mensagem_telegram(
            {
                "total_kits_unicos": 50,
                "total_vendas": 5000,
                "preco_min": 30.0,
                "preco_max": 120.0,
                "preco_medio": 55.0,
                "termos_varridos": 3,
                "ranking_marcas": [
                    {"marca": "Impala", "vendidos": 3000, "anuncios": 20, "preco_medio": 58.0},
                    {"marca": "Anita", "vendidos": 1500, "anuncios": 15, "preco_medio": 42.0},
                ],
                "padroes_tamanho": [{"qtd": 10, "anuncios": 12, "vendidos": 2000, "preco_medio": 69.0}],
                "top_vendas": [
                    {
                        "titulo": "Kit 10 Impala",
                        "preco": 69.0,
                        "quantidade_vendida": 500,
                        "marca": "Impala",
                    }
                ],
            },
            [{"ok": True, "nome": "Kits Impala", "termo_busca": "x", "total_kits": 10, "total_bruto": 12}],
        )
        self.assertIn("Impala", msg)
        self.assertIn("500", msg)
        self.assertIn("Kit 10", msg)


if __name__ == "__main__":
    unittest.main()
