"""
tests/test_api_autenticacao.py — middleware de autenticação por API key (api/app.py).
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.app import app


class TestApiAutenticacao(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("api.app.ROBO_API_KEY", "")
    def test_sem_chave_configurada_permite_acesso_aberto(self):
        """Compatibilidade: sem ROBO_API_KEY definida, comportamento é o mesmo de antes desta mudança."""
        resp = self.client.post("/marketplaces/keepalive", json={})
        self.assertNotEqual(resp.status_code, 401)

    @patch("api.app.ROBO_API_KEY", "segredo-123")
    def test_chave_configurada_bloqueia_sem_header(self):
        resp = self.client.post("/marketplaces/keepalive", json={})
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(resp.get_json()["ok"])

    @patch("api.app.ROBO_API_KEY", "segredo-123")
    def test_chave_configurada_bloqueia_header_errado(self):
        resp = self.client.post(
            "/marketplaces/keepalive", json={}, headers={"X-API-Key": "chave-errada"}
        )
        self.assertEqual(resp.status_code, 401)

    @patch("api.app.ROBO_API_KEY", "segredo-123")
    def test_chave_configurada_permite_header_correto(self):
        resp = self.client.post(
            "/marketplaces/keepalive", json={}, headers={"X-API-Key": "segredo-123"}
        )
        self.assertNotEqual(resp.status_code, 401)

    @patch("api.app.ROBO_API_KEY", "segredo-123")
    def test_health_nunca_exige_chave(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)

    @patch("api.app.ROBO_API_KEY", "segredo-123")
    def test_faturamento_nfe_bloqueado_sem_chave(self):
        """O endpoint mais sensível (emite NF-e real) também passa pela autenticação."""
        resp = self.client.post(
            "/faturamento/nfe",
            json={"dry_run": True, "pedido": {"pedido_id": "1", "itens": []}},
        )
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
