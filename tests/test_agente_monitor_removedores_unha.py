"""
tests/test_agente_monitor_removedores_unha.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.esmaltes import agente_monitor_removedores_unha as agente


class AgenteMonitorRemovedoresUnhaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "avaliar_busca_removedores", return_value=None)
    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "buscar_removedores_segmento")
    @patch.object(agente, "_carregar_termos")
    def test_executar_envia_ranking_telegram(self, mock_termos, mock_busca, mock_alertar, _mock_ia):
        mock_termos.return_value = [
            {
                "id": "cruzeiro",
                "ativo": True,
                "nome": "Cruzeiro",
                "termo_busca": "acetona cruzeiro",
                "limite_resultados": 10,
                "prioridade": 1,
            },
            {
                "id": "impala",
                "ativo": True,
                "nome": "Impala",
                "termo_busca": "acetona impala",
                "limite_resultados": 10,
                "prioridade": 1,
            },
        ]
        mock_busca.side_effect = [
            (
                [
                    {
                        "item_id": "MLB1",
                        "titulo": "Removedor Acetona Cruzeiro 500ml",
                        "nome_produto": "Removedor Acetona Cruzeiro 500ml",
                        "fabricante": "Cruzeiro",
                        "preco": 28.0,
                        "quantidade_vendida": 600,
                        "volume_ml": 500,
                    }
                ],
                "acetona cruzeiro",
                5,
            ),
            (
                [
                    {
                        "item_id": "MLB2",
                        "titulo": "Acetona Impala 100ml profissional",
                        "nome_produto": "Acetona Impala 100ml profissional",
                        "fabricante": "Impala",
                        "preco": 11.0,
                        "quantidade_vendida": 150,
                        "volume_ml": 100,
                    }
                ],
                "acetona impala",
                3,
            ),
        ]

        with patch.object(agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"), patch.object(
            agente, "HISTORY_PATH", self.tmp_path / "hist.json"
        ), patch.object(agente, "REMOVEDORES_UNHA_PAUSA_SEG", 0), patch.object(
            agente, "REMOVEDORES_UNHA_IA_AVALIAR", False
        ):
            out = agente.executar(enviar_alerta=True)

        self.assertTrue(out["ok"])
        self.assertEqual(out["consolidado"]["total_produtos_unicos"], 2)
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("Ranking por fabricante", msg)
        self.assertIn("Cruzeiro", msg)
        self.assertIn("bruto", msg)

    def test_montar_mensagem(self):
        msg = agente.montar_mensagem_telegram(
            {
                "total_produtos_unicos": 30,
                "total_vendas": 3000,
                "preco_min": 8.0,
                "preco_max": 45.0,
                "preco_medio": 18.0,
                "ranking_fabricantes": [
                    {"rank": 1, "fabricante": "Cruzeiro", "vendidos": 2000, "anuncios": 15, "preco_medio": 16.0},
                ],
                "top_vendas": [
                    {
                        "rank_vendas": 1,
                        "nome_produto": "Removedor Cruzeiro 500ml",
                        "fabricante": "Cruzeiro",
                        "preco": 28.0,
                        "quantidade_vendida": 500,
                        "volume_ml": 500,
                    }
                ],
            },
            [
                {
                    "ok": True,
                    "nome": "Cruzeiro",
                    "termo_busca": "x",
                    "termo_usado": "acetona cruzeiro",
                    "total_removedores": 5,
                    "total_bruto": 8,
                }
            ],
            avaliacao_ia={
                "resumo_situacao": "Busca melhorou com termos curtos.",
                "segmentos": [
                    {
                        "segmento_id": "cruzeiro",
                        "termo_busca_sugerido": "acetona cruzeiro",
                        "confianca": "alta",
                        "motivo": "Termo curto funciona no ML.",
                    }
                ],
            },
        )
        self.assertIn("🥇", msg)
        self.assertIn("Claude", msg)
        self.assertIn("bruto", msg)


if __name__ == "__main__":
    unittest.main()
