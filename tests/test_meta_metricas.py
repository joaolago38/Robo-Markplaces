import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.social.agente_metricas_meta import executar


class MetaMetricasTests(unittest.TestCase):
    @patch("agentes.social.agente_metricas_meta.alertar_gestor")
    @patch("agentes.social.agente_metricas_meta.listar_metricas_campanhas")
    def test_classifica_campanha_critica(self, mock_listar, _mock_alertar):
        mock_listar.return_value = [
            {
                "campaign_id": "1",
                "campaign_name": "Campanha Teste",
                "spend": "120.0",
                "cpc": "2.5",
                "ctr": "0.5",
                "frequency": "4.0",
                "actions": [{"action_type": "purchase", "value": "1"}],
                "action_values": [{"action_type": "purchase", "value": "60.0"}],
            }
        ]
        out = executar(alertar_quando_atencao=False, periodo_dias=1)
        self.assertEqual(out["resumo"]["total"], 1)
        self.assertEqual(out["campanhas"][0]["status"], "critico")

    @patch("agentes.social.agente_metricas_meta.listar_metricas_campanhas")
    def test_classifica_campanha_saudavel(self, mock_listar):
        mock_listar.return_value = [
            {
                "campaign_id": "2",
                "campaign_name": "Campanha Boa",
                "spend": "100.0",
                "cpc": "1.0",
                "ctr": "2.0",
                "frequency": "2.0",
                "actions": [{"action_type": "purchase", "value": "5"}],
                "action_values": [{"action_type": "purchase", "value": "350.0"}],
            }
        ]
        out = executar(alertar_quando_atencao=False, periodo_dias=1)
        self.assertEqual(out["campanhas"][0]["status"], "saudavel")


if __name__ == "__main__":
    unittest.main()
