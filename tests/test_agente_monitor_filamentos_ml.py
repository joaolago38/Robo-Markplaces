"""
tests/test_agente_monitor_filamentos_ml.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.filamentos import agente_monitor_filamentos_ml as agente


class AgenteMonitorFilamentosMlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente.ml_client, "buscar_concorrentes_por_termo")
    @patch.object(agente, "_carregar_termos")
    def test_executar_envia_telegram(self, mock_termos, mock_busca, mock_alertar):
        mock_termos.return_value = [
            {
                "id": "fil-pla",
                "ativo": True,
                "nome": "PLA 1kg",
                "material": "PLA",
                "termo_busca": "filamento pla 1kg",
                "limite_resultados": 10,
                "prioridade": 1,
            }
        ]
        mock_busca.return_value = [
            {
                "item_id": "MLB1",
                "titulo": "Printalot Filamento PLA preto 1kg",
                "preco": 79.9,
                "quantidade_vendida": 200,
            }
        ]

        with patch.object(agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"), patch.object(
            agente, "HISTORY_PATH", self.tmp_path / "hist.json"
        ), patch.object(agente, "SERIES_PATH", self.tmp_path / "series.json"), patch.object(
            agente, "GRAFICO_PATH", self.tmp_path / "g.png"
        ), patch.object(agente, "enviar_foto_gestor", return_value=True), patch.object(
            agente, "gestor_telegram_configurado", return_value=True
        ), patch.object(agente, "FILAMENTOS_ML_PAUSA_SEG", 0), patch.object(
            agente, "FILAMENTOS_ML_CRUZAR_ALIBABA", False
        ):
            out = agente.executar(enviar_alerta=True)

        self.assertTrue(out["ok"])
        self.assertEqual(out["consolidado"]["total_filamentos_unicos"], 1)
        self.assertEqual(out["consolidado"]["ranking_cores"][0]["cor"], "Preto")
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("Cores mais vendidas", msg)
        self.assertIn("Marcas que mais vendem", msg)

    def test_montar_mensagem(self):
        msg = agente.montar_mensagem_telegram(
            {
                "total_filamentos_unicos": 12,
                "total_vendas": 900,
                "preco_min": 59.0,
                "preco_max": 149.0,
                "preco_medio": 89.0,
                "termos_varridos": 2,
                "ranking_cores": [
                    {"cor": "Preto", "vendidos": 400, "anuncios": 5, "preco_medio": 85.0}
                ],
                "ranking_marcas": [
                    {"marca": "eSUN", "vendidos": 500, "anuncios": 4, "preco_medio": 85.0}
                ],
                "ranking_materiais": [
                    {"material": "PLA", "vendidos": 700, "anuncios": 8, "preco_medio": 80.0}
                ],
                "top_baratos": [
                    {
                        "titulo": "Filamento PLA barato",
                        "preco": 59.0,
                        "marca": "Genérico/Outros",
                        "cor": "Preto",
                    }
                ],
                "top_vendas": [
                    {
                        "titulo": "eSUN PLA 1kg",
                        "preco": 89.0,
                        "quantidade_vendida": 400,
                        "marca": "eSUN",
                        "cor": "Preto",
                    }
                ],
            },
            [
                {
                    "ok": True,
                    "nome": "PLA 1kg",
                    "preco_min": 59,
                    "preco_max": 120,
                    "preco_medio": 85,
                    "total_filamentos": 8,
                    "total_bruto": 10,
                }
            ],
            cruzamento={
                "ok": True,
                "cores_usadas": ["Preto"],
                "cambio_usd_brl": 5.5,
                "cruzamentos": [],
            },
        )
        self.assertIn("eSUN", msg)
        self.assertIn("Cores mais vendidas", msg)
        self.assertIn("Cruzamento Alibaba", msg)


if __name__ == "__main__":
    unittest.main()
