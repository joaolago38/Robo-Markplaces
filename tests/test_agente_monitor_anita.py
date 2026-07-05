"""
tests/test_agente_monitor_anita.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.esmaltes import agente_monitor_anita as agente


class AgenteMonitorAnitaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hist = Path(self.tmp.name) / "hist.json"

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "ml_client")
    @patch.object(agente, "_carregar_produtos")
    def test_fluxo_completo(self, mock_prod, mock_ml, _mock_alertar):
        mock_prod.return_value = [
            {
                "id": "p1",
                "ativo": True,
                "prioridade": 1,
                "nome": "Kit 5 Anita",
                "tipo": "kit",
                "termo_busca": "kit 5 anita",
                "qtd_esmaltes_preferencia": 5,
                "cores_preferencia": ["Nude"],
                "meu_preco": 48.90,
                "custo_total": 24.0,
                "taxa_marketplace_pct": 18,
                "limite_resultados": 10,
            }
        ]
        mock_ml.buscar_concorrentes_por_termo.return_value = [
            {"titulo": "Kit 5 Esmaltes Anita Nude", "preco": 45.0, "quantidade_vendida": 120},
            {"titulo": "Kit 5 Impala Bailarina", "preco": 42.0, "quantidade_vendida": 200},
        ]
        with patch.object(agente, "HISTORY_PATH", self.hist), patch.object(
            agente, "ANITA_PAUSA_ENTRE_BUSCAS_SEG", 0
        ):
            out = agente.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_produtos"], 1)
        self.assertTrue(out["alerta_enviado"])

    def test_montar_painel(self):
        msg = agente._montar_painel(
            [
                {
                    "nome": "Kit 5 Anita",
                    "prioridade": 1,
                    "tipo": "kit",
                    "meu_preco": 48.90,
                    "total_anuncios": 5,
                    "total_anita": 2,
                    "marca_mais_vendida": "Impala",
                    "menor_preco_anita": 44.0,
                    "margem_minha": {"margem_operacional_pct": 32.5, "lucro_reais": 15.9},
                    "divergencias_kit": 1,
                    "divergencias_cor": 0,
                    "ranking_marcas": [
                        {"marca": "Impala", "vendidos": 200, "anuncios": 3},
                        {"marca": "Anita", "vendidos": 120, "anuncios": 2},
                    ],
                    "analises": [],
                }
            ]
        )
        self.assertIn("Anita", msg)
        self.assertIn("margem", msg)
        self.assertIn("Impala", msg)


if __name__ == "__main__":
    unittest.main()
