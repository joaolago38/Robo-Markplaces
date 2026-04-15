"""
tests/test_behaviors.py
Testes de comportamento contra o código real da API.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.app import app
from agentes.social.publicador import selecionar_produto


class ApiBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("api.app.alertar_critico")
    def test_B03_repricing_respeita_margem(self, mock_alerta):
        resp = self.client.post(
            "/repricing",
            json={"sku": "ESM-001", "preco_atual": 9.9, "custo": 6.0, "preco_concorrente": 4.0},
        )
        data = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(data["ajustar"])
        self.assertTrue(data["alertado"])
        mock_alerta.assert_called_once()

    def test_repricing_rejeita_payload_invalido(self):
        resp = self.client.post(
            "/repricing",
            json={"sku": "ESM-001", "preco_atual": "abc", "custo": 6.0, "preco_concorrente": 4.0},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("numérico", resp.get_json()["erro"])

    @patch("api.app.alertar_gestor")
    def test_B07_campanha_pausada_ctr_baixo(self, mock_alerta):
        resp = self.client.post("/campanha/avaliar", json={"nome": "Campanha X", "cpc": 1.0, "ctr": 0.2, "roas": 2.0})
        data = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["acao"], "pausar")
        self.assertIn("CTR", data["motivo"])
        mock_alerta.assert_called_once()

    @patch("api.app.listar_produtos")
    @patch("api.app.gerar_post")
    def test_B08_post_exige_estoque_minimo(self, mock_gerar_post, mock_listar_produtos):
        mock_listar_produtos.return_value = [
            {"nome": "A", "preco": 10, "custo": 9, "estoque": 5},
            {"nome": "B", "preco": 20, "custo": 5, "estoque": 50},
            {"nome": "C", "preco": 30, "custo": 28, "estoque": 25},
        ]
        mock_gerar_post.return_value = "promo"

        resp = self.client.post("/post", json={"canal": "instagram"})
        data = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["produto"]["nome"], "B")


class SocialAgentTests(unittest.TestCase):
    @patch("agentes.social.publicador.listar_produtos")
    def test_selecionar_produto_por_margem(self, mock_listar_produtos):
        mock_listar_produtos.return_value = [
            {"nome": "A", "preco": 20, "custo": 18, "estoque": 100},
            {"nome": "B", "preco": 15, "custo": 5, "estoque": 100},
        ]
        produto = selecionar_produto()
        self.assertEqual(produto["nome"], "B")


if __name__ == "__main__":
    unittest.main()
