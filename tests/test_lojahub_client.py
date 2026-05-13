"""
tests/test_lojahub_client.py — LH01–LH07
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.lojahub import lojahub_client


def _mock_resp(body: dict) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    return r


class TestLojahubClient(unittest.TestCase):
    @patch.object(lojahub_client, "LOJAHUB_TOKEN", "")
    def test_LH01_pedidos_pendentes_sem_token(self, *_patches):
        self.assertEqual(lojahub_client.listar_pedidos_pendentes(), [])

    @patch.object(lojahub_client, "LOJAHUB_TOKEN", "t")
    @patch.object(lojahub_client, "request")
    def test_LH02_pedidos_pendentes_sucesso(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"data": [{"id": "p1", "status": "pending"}]})
        pedidos = lojahub_client.listar_pedidos_pendentes()
        self.assertEqual(pedidos[0]["id"], "p1")

    @patch.object(lojahub_client, "LOJAHUB_TOKEN", "t")
    @patch.object(lojahub_client, "request", side_effect=Exception("boom"))
    def test_LH03_pedidos_pendentes_excecao(self, *_patches):
        self.assertEqual(lojahub_client.listar_pedidos_pendentes(), [])

    @patch.object(lojahub_client, "LOJAHUB_TOKEN", "t")
    @patch.object(lojahub_client, "request")
    def test_LH04_prontos_faturar_params_approved(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"data": [{"id": "p2", "status": "approved"}]})
        pedidos = lojahub_client.listar_pedidos_prontos_faturar()
        self.assertEqual(len(pedidos), 1)
        params = mock_request.call_args[1]["params"]
        self.assertEqual(params.get("status"), "approved")

    @patch.object(lojahub_client, "LOJAHUB_TOKEN", "t")
    @patch.object(lojahub_client, "request")
    def test_LH05_resumo_ok(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"data": {"receita": 500.0, "pedidos": 5}})
        resumo = lojahub_client.listar_resumo_vendas_24h()
        self.assertTrue(resumo["ok"])
        self.assertEqual(resumo["data"]["receita"], 500.0)

    @patch.object(lojahub_client, "LOJAHUB_TOKEN", "")
    def test_LH06_resumo_sem_token(self, *_patches):
        resumo = lojahub_client.listar_resumo_vendas_24h()
        self.assertFalse(resumo["ok"])

    @patch.object(lojahub_client, "LOJAHUB_TOKEN", "t")
    @patch.object(lojahub_client, "request", side_effect=Exception("timeout"))
    def test_LH07_resumo_excecao(self, *_patches):
        resumo = lojahub_client.listar_resumo_vendas_24h()
        self.assertFalse(resumo["ok"])
        self.assertIn("erro", resumo)


if __name__ == "__main__":
    unittest.main()
