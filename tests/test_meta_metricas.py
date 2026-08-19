import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.social.agente_metricas_meta import executar


class MetaMetricasTests(unittest.TestCase):
    @patch("agentes.social.agente_metricas_meta.escrever_json_atomico")
    @patch("agentes.social.agente_metricas_meta.coletar_receita_ml", return_value={"ok": True, "receita_ml": 0, "pedidos_ml": 0})
    @patch("agentes.social.agente_metricas_meta.emitir_metricas_ciclo_meta", return_value={"pronto": False})
    @patch("agentes.social.agente_metricas_meta.listar_metricas_por_plataforma", return_value=[])
    @patch("agentes.social.agente_metricas_meta.alertar_gestor")
    @patch("agentes.social.agente_metricas_meta.listar_metricas_campanhas")
    def test_classifica_campanha_critica(self, mock_listar, _mock_alertar, *_mocks):
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

    @patch("agentes.social.agente_metricas_meta.escrever_json_atomico")
    @patch("agentes.social.agente_metricas_meta.coletar_receita_ml", return_value={"ok": True, "receita_ml": 0, "pedidos_ml": 0})
    @patch("agentes.social.agente_metricas_meta.emitir_metricas_ciclo_meta", return_value={"pronto": False})
    @patch("agentes.social.agente_metricas_meta.listar_metricas_por_plataforma", return_value=[])
    @patch("agentes.social.agente_metricas_meta.listar_metricas_campanhas")
    def test_classifica_campanha_saudavel(self, mock_listar, _plat, _emit, _ml, mock_hb):
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
        mock_hb.assert_called_once()
        snap = mock_hb.call_args[0][1]
        self.assertIn("timestamp", snap)
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["campanhas"], 1)
        self.assertFalse(snap["pronto"])


if __name__ == "__main__":
    unittest.main()
