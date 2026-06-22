"""
tests/test_agente_ads_gatilho.py
Testa cálculo de ACOS agregado e pausa seletiva por campanha.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.ml import agente_ads_gatilho as gatilho


class TestAcosAgregado(unittest.TestCase):
    @patch.object(gatilho, "listar_campanhas", return_value=[
        {"id": "C1", "acos": 0.40, "cost": 80},
        {"id": "C2", "acos": 0.10, "cost": 20},
        {"id": "C3", "acos": 0.50, "cost": 0},
    ])
    def test_calcular_acos_agregado_ponderado(self, *_):
        acos = gatilho._calcular_acos_agregado()
        self.assertAlmostEqual(acos, (0.40 * 80 + 0.10 * 20) / 100, places=4)

    @patch.object(gatilho, "listar_campanhas", return_value=[])
    def test_calcular_acos_sem_campanhas(self, *_):
        self.assertEqual(gatilho._calcular_acos_agregado(), 0.0)


class TestPausaSeletiva(unittest.TestCase):
    @patch.object(gatilho, "campanhas_acos_acima_limite", return_value=[
        {"id": "C_ALTO", "acos": 0.35, "cost": 50},
    ])
    @patch.object(gatilho, "aplicar_decisao_campanhas", return_value=[{"ok": True}])
    @patch.object(gatilho, "alertar_gestor")
    def test_pausar_passa_somente_campanhas_acima_limite(self, *_mocks):
        resultado = {
            "decisao": "pausar",
            "confirmado_gestor": True,
            "budget_sugerido_dia": 0,
        }
        gatilho._executar_api_se_aprovado(resultado)
        gatilho.aplicar_decisao_campanhas.assert_called_once()
        kwargs = gatilho.aplicar_decisao_campanhas.call_args.kwargs
        self.assertEqual(kwargs.get("campaign_ids"), ["C_ALTO"])

    @patch.object(gatilho, "aplicar_decisao_campanhas", return_value=[{"ok": True}])
    @patch.object(gatilho, "alertar_gestor")
    def test_ligar_nao_filtra_por_campaign_ids(self, *_mocks):
        resultado = {
            "decisao": "ligar",
            "confirmado_gestor": True,
            "budget_sugerido_dia": 10,
        }
        gatilho._executar_api_se_aprovado(resultado)
        kwargs = gatilho.aplicar_decisao_campanhas.call_args.kwargs
        self.assertNotIn("campaign_ids", kwargs)


    @patch.object(gatilho, "campanhas_acos_acima_limite", return_value=[
        {"id": "C1", "cost": 30.0},
    ])
    @patch.object(gatilho, "perguntar_gestor_e_aguardar", return_value=False)
    @patch.object(gatilho, "alertar_gestor")
    def test_pausar_inclui_gasto_diario_estimado(self, *_mocks):
        out = gatilho.avaliar_momento_ads(avaliacoes=30, nota_media=4.9, acos_atual=0.35)
        self.assertEqual(out["decisao"], "manter")
        self.assertGreater(out.get("gasto_diario_estimado_evitado", 0), 0)


if __name__ == "__main__":
    unittest.main()
