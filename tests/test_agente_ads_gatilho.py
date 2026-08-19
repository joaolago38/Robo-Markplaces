"""
tests/test_agente_ads_gatilho.py
Testa cálculo de ACOS agregado e pausa seletiva por campanha.
"""
import os
import sys
import unittest
from datetime import datetime
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
        self.assertEqual(kwargs.get("budget"), 10.0)


    @patch.object(gatilho, "probe_escrita_product_ads", return_value={"ok": True, "codigo": "ok"})
    @patch.object(gatilho, "campanhas_acos_acima_limite", return_value=[
        {"id": "C1", "cost": 30.0},
    ])
    @patch.object(gatilho, "aplicar_decisao_campanhas", return_value=[{"ok": True}])
    @patch.object(gatilho, "perguntar_gestor_e_aguardar")
    @patch.object(gatilho, "alertar_gestor")
    def test_pausar_inclui_gasto_diario_estimado(self, mock_alerta, mock_pergunta, *_mocks):
        out = gatilho.avaliar_momento_ads(avaliacoes=30, nota_media=4.9, acos_atual=0.35)
        self.assertEqual(out["decisao"], "pausar")
        self.assertTrue(out.get("auto_pausar_acos"))
        self.assertGreater(out.get("gasto_diario_estimado_evitado", 0), 0)
        mock_pergunta.assert_not_called()


class TestContextoDecisaoAds(unittest.TestCase):
    @patch("agentes.ml.agente_ads_gatilho.datetime")
    def test_sazonalidade_out_dez_no_contexto(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 11, 15)
        ctx = gatilho._contexto_decisao_ads(
            "escalar", 30, 4.9, 0.1, True, 50.0,
            ["Pico sazonal (Out-Dez) — escalar agressivo"],
        )
        self.assertTrue(ctx.get("sazonalidade_out_dez"))

    @patch.object(gatilho, "probe_escrita_product_ads", return_value={"ok": True, "codigo": "ok"})
    @patch.object(gatilho, "perguntar_gestor_e_aguardar", return_value=False)
    @patch.object(gatilho, "alertar_gestor")
    @patch("agentes.ml.agente_ads_gatilho.datetime")
    @patch("integracoes.ml.contrato_impulso_ml.ads_pode_ligar", return_value=(True, "teste"))
    @patch("integracoes.ml.contrato_impulso_ml.montar_contrato", return_value={"ok": True})
    def test_escalar_passa_contexto_decisao(self, _montar, _ads, mock_dt, mock_alerta, mock_pergunta, _probe):
        mock_dt.now.return_value = datetime(2026, 11, 15)
        gatilho.avaliar_momento_ads(avaliacoes=30, nota_media=4.9, acos_atual=0.1, full_ativo=True)
        self.assertTrue(mock_pergunta.called)
        kwargs = mock_pergunta.call_args.kwargs
        self.assertIn("contexto_decisao", kwargs)
        self.assertTrue(kwargs["contexto_decisao"].get("sazonalidade_out_dez"))


class TestExecutarFullLogistico(unittest.TestCase):
    @patch.object(gatilho, "_metricas_e_heartbeat")
    @patch.object(gatilho, "avaliar_momento_ads", return_value={"decisao": "aguardar"})
    @patch.object(gatilho, "_calcular_acos_agregado", return_value=0.1)
    @patch.object(
        gatilho,
        "buscar_reputacao_vendedor",
        return_value={
            "metrics": {"total_ratings": 10, "average_rating": 4.8},
            "power_seller_status": "gold",
        },
    )
    @patch("integracoes.ml.ml_client.listar_meus_anuncios", return_value=[])
    def test_executar_lider_sem_full_nao_marca_full(self, _listar, _rep, _acos, mock_avaliar, _hb):
        gatilho.executar()
        self.assertFalse(mock_avaliar.call_args.args[3])

    @patch.object(gatilho, "_metricas_e_heartbeat")
    @patch.object(gatilho, "avaliar_momento_ads", return_value={"decisao": "aguardar"})
    @patch.object(gatilho, "_calcular_acos_agregado", return_value=0.1)
    @patch.object(
        gatilho,
        "buscar_reputacao_vendedor",
        return_value={"metrics": {"total_ratings": 10, "average_rating": 4.8}},
    )
    @patch(
        "integracoes.ml.ml_client.listar_meus_anuncios",
        return_value=[{"logistic_type": "fulfillment", "listing_type_id": "gold_special"}],
    )
    def test_executar_detecta_full_pela_logistica(self, _listar, _rep, _acos, mock_avaliar, _hb):
        gatilho.executar()
        self.assertTrue(mock_avaliar.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
