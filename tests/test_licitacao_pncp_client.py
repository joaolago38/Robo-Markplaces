"""
tests/test_licitacao_pncp_client.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.licitacao import pncp_client as pncp


class PncpClientTests(unittest.TestCase):
    @patch("integracoes.licitacao.pncp_client.request")
    def test_buscar_propostas_abertas_ok(self, mock_request):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": [{"objetoCompra": "teste"}], "paginasRestantes": 0}
        mock_request.return_value = resp
        out = pncp.buscar_propostas_abertas(codigo_modalidade=6, pagina=1)
        self.assertEqual(len(out.get("data", [])), 1)

    @patch("integracoes.licitacao.pncp_client.request")
    def test_buscar_detalhe_compra(self, mock_request):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"valorTotalEstimado": 1000.0}
        mock_request.return_value = resp
        out = pncp.buscar_detalhe_compra("12345678000199", 2026, 1)
        self.assertEqual(out.get("valorTotalEstimado"), 1000.0)


    @patch("integracoes.licitacao.pncp_client.request")
    def test_buscar_publicacoes(self, mock_request):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": [], "paginasRestantes": 0}
        mock_request.return_value = resp
        out = pncp.buscar_publicacoes_recentes(codigo_modalidade=6)
        self.assertIn("data", out)

    @patch("integracoes.licitacao.pncp_client.request")
    def test_erro_http_retorna_vazio(self, mock_request):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "erro"
        mock_request.return_value = resp
        self.assertEqual(pncp.buscar_propostas_abertas(codigo_modalidade=6), {})


if __name__ == "__main__":
    unittest.main()
