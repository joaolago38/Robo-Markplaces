"""
tests/test_api_endpoints.py — EP01–EP09
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.app import app


class TestApiEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_EP01_health_ok(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "ok")

    @patch("api.app.executar_manutencao_marketplaces", return_value={"resultados": []})
    def test_EP02_keepalive_200(self, *_patches):
        resp = self.client.post("/marketplaces/keepalive", json={})
        self.assertEqual(resp.status_code, 200)

    @patch("api.app.executar_sincronizar_estoque", return_value={"total_ajustes": 0, "dry_run": True})
    def test_EP12_estoque_sincronizar_200(self, *_patches):
        resp = self.client.post("/marketplaces/estoque/sincronizar", json={"dry_run": True})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    @patch("api.app.executar_algoritmo_marketplaces", return_value={"resumo": {}})
    def test_EP03_algoritmo_ajustar_200(self, *_patches):
        resp = self.client.post("/marketplaces/algoritmo/ajustar", json={})
        self.assertEqual(resp.status_code, 200)

    @patch("api.app.emitir_nfe_pedido", return_value={"ok": True, "dry_run": True})
    def test_EP04_faturamento_nfe_200(self, *_patches):
        resp = self.client.post(
            "/faturamento/nfe",
            json={
                "dry_run": True,
                "pedido": {"pedido_id": "P1", "itens": [], "cliente": {}},
            },
        )
        self.assertEqual(resp.status_code, 200)

    @patch("api.app.executar_metricas_meta", return_value={"total_campanhas": 0})
    def test_EP05_meta_validar_200(self, *_patches):
        resp = self.client.post("/meta/campanhas/validar", json={})
        self.assertEqual(resp.status_code, 200)

    @patch("api.app.analisar_monitor_ml", return_value={"ok": True, "resumo": "ok"})
    def test_EP10_ml_ads_diagnostico_200(self, *_patches):
        resp = self.client.post("/ml/ads/diagnostico", json={"enviar_alerta": False})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    @patch("api.app.analisar_monitor_ml", return_value={"ok": False, "motivo": "ML não configurado"})
    def test_EP11_ml_ads_diagnostico_503(self, *_patches):
        resp = self.client.post("/ml/ads/diagnostico", json={})
        self.assertEqual(resp.status_code, 503)
        self.assertFalse(resp.get_json()["ok"])

    @patch("api.app.executar_repricing_marketplaces", return_value={"ajustes": []})
    def test_EP06_monitorar_produtos_200(self, *_patches):
        resp = self.client.post("/marketplaces/produtos/monitorar", json={"dry_run": True})
        self.assertEqual(resp.status_code, 200)

    @patch("api.app.executar_operacao_24h", return_value={"kpis_24h": {}})
    def test_EP07_operacao_24h_200(self, *_patches):
        resp = self.client.post("/operacao/24h", json={})
        self.assertEqual(resp.status_code, 200)

    def test_EP08_chat_sem_pergunta_400(self):
        resp = self.client.post("/chat", json={"item_id": "MLB1"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("erro", resp.get_json())

    def test_EP09_repricing_nao_numerico_400(self):
        resp = self.client.post(
            "/repricing",
            json={"sku": "X", "preco_atual": "abc", "custo": 5, "preco_concorrente": 4},
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
