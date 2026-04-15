import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.social.agente_trafego_manicures import executar, executar_resumo_madrugada


class TrafegoManicuresTests(unittest.TestCase):
    @patch("agentes.social.agente_trafego_manicures.alertar_gestor")
    @patch("agentes.social.agente_trafego_manicures.listar_metricas_campanhas")
    def test_prioriza_impala_anita_kits(self, mock_listar, _mock_alerta):
        mock_listar.return_value = [
            {
                "campaign_id": "1",
                "campaign_name": "Impala Profissional Manicures",
                "spend": "100.0",
                "cpc": "1.0",
                "ctr": "2.0",
                "frequency": "2.0",
                "actions": [{"action_type": "purchase", "value": "4"}],
                "action_values": [{"action_type": "purchase", "value": "280.0"}],
            },
            {
                "campaign_id": "2",
                "campaign_name": "Kit Anita Completo",
                "spend": "100.0",
                "cpc": "1.2",
                "ctr": "1.6",
                "frequency": "2.0",
                "actions": [{"action_type": "purchase", "value": "3"}],
                "action_values": [{"action_type": "purchase", "value": "240.0"}],
            },
        ]

        out = executar(periodo_dias=1, alertar_todo_relatorio=True)
        self.assertEqual(out["total_campanhas"], 2)
        self.assertIn("impala", out["resumo_grupos"])
        self.assertIn("anita", out["resumo_grupos"])
        self.assertIn("kits", out["resumo_grupos"])
        self.assertGreater(out["eficiencia_media_priorizadas"], 0)

    @patch("agentes.social.agente_trafego_manicures.alertar_gestor")
    @patch("agentes.social.agente_trafego_manicures.listar_metricas_campanhas")
    def test_resumo_madrugada_top3(self, mock_listar, _mock_alerta):
        mock_listar.return_value = [
            {"campaign_id": "1", "campaign_name": "Impala A", "spend": "100", "cpc": "3", "ctr": "0.5", "frequency": "5", "actions": [], "action_values": []},
            {"campaign_id": "2", "campaign_name": "Anita B", "spend": "100", "cpc": "2.5", "ctr": "0.8", "frequency": "4", "actions": [], "action_values": []},
            {"campaign_id": "3", "campaign_name": "Kit C", "spend": "100", "cpc": "2.0", "ctr": "1.0", "frequency": "3.5", "actions": [], "action_values": []},
            {"campaign_id": "4", "campaign_name": "Campanha D", "spend": "100", "cpc": "1.0", "ctr": "2.0", "frequency": "2", "actions": [], "action_values": []},
        ]
        out = executar_resumo_madrugada(periodo_dias=1)
        self.assertEqual(len(out["top3_piores"]), 3)


if __name__ == "__main__":
    unittest.main()
