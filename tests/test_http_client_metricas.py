"""
tests/test_http_client_metricas.py — instrumentação Datadog em core/http_client.request().
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import http_client


class TestHttpClientMetricas(unittest.TestCase):
    @patch("core.http_client.incrementar")
    @patch("core.http_client.gauge")
    @patch("core.http_client._SESSION.request")
    def test_sucesso_2xx_emite_latencia_sem_erro(self, mock_request, mock_gauge, mock_incrementar):
        mock_request.return_value = MagicMock(status_code=200)

        resp = http_client.request("GET", "https://api.bling.com.br/produtos")

        self.assertEqual(resp.status_code, 200)
        mock_gauge.assert_called_once()
        tags = mock_gauge.call_args.kwargs.get("tags") or mock_gauge.call_args.args[-1]
        self.assertIn("host:api.bling.com.br", tags)
        self.assertIn("status:2xx", tags)
        self.assertIn("origem:api", tags)
        mock_incrementar.assert_not_called()

    @patch("core.http_client.incrementar")
    @patch("core.http_client.gauge")
    @patch("core.http_client._SESSION.request")
    def test_status_4xx_incrementa_erro(self, mock_request, mock_gauge, mock_incrementar):
        mock_request.return_value = MagicMock(status_code=401)

        http_client.request("GET", "https://api.mercadolibre.com/items")

        mock_incrementar.assert_called_once()
        nome = mock_incrementar.call_args.args[0]
        self.assertEqual(nome, "http.erro")

    @patch("core.http_client.incrementar")
    @patch("core.http_client.gauge")
    @patch("core.http_client._SESSION.request", side_effect=RuntimeError("timeout"))
    def test_excecao_propaga_e_incrementa_exception(self, mock_request, mock_gauge, mock_incrementar):
        with self.assertRaises(RuntimeError):
            http_client.request("POST", "https://api.magalu.com/oauth/token")

        mock_incrementar.assert_called_once()
        self.assertEqual(mock_incrementar.call_args.args[0], "http.exception")

    @patch("core.http_client.incrementar")
    @patch("core.http_client.gauge")
    @patch("core.http_client.log_erros_veiculos_ativos", return_value=False)
    @patch("core.http_client._SESSION.request", side_effect=RuntimeError("timeout"))
    def test_scraper_silenciado_nao_emite_metricas(
        self, _mock_request, _log, mock_gauge, mock_incrementar
    ):
        with self.assertRaises(RuntimeError):
            http_client.request("GET", "https://www.leopardoveiculos.com.br/x")
        mock_gauge.assert_not_called()
        mock_incrementar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
