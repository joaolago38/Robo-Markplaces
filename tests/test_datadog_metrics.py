"""
tests/test_datadog_metrics.py — cliente de métricas customizadas (Metrics API v2).
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import datadog_metrics


class TestDatadogMetrics(unittest.TestCase):
    @patch("core.datadog_metrics.requests.post")
    @patch("core.config.DD_API_KEY", "")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_sem_api_key_nao_chama_http(self, mock_post, *_):
        datadog_metrics.incrementar("teste.evento")
        mock_post.assert_not_called()

    @patch("core.datadog_metrics.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    @patch("core.config.DD_SITE", "datadoghq.com")
    @patch("core.config.DD_ENV", "production")
    def test_incrementar_monta_payload_count(self, mock_post, *_):
        datadog_metrics.incrementar("token.renovado", tags=["provider:bling"])

        mock_post.assert_called_once()
        url = mock_post.call_args.args[0]
        self.assertIn("api.datadoghq.com/api/v2/series", url)

        body = json.loads(mock_post.call_args.kwargs["data"])
        serie = body["series"][0]
        self.assertEqual(serie["metric"], "robo.token.renovado")
        self.assertEqual(serie["type"], 1)
        self.assertIn("env:production", serie["tags"])
        self.assertIn("provider:bling", serie["tags"])
        self.assertEqual(serie["points"][0]["value"], 1.0)

    @patch("core.datadog_metrics.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_gauge_monta_payload_gauge(self, mock_post, *_):
        datadog_metrics.gauge("http.latencia_ms", 123.4, tags=["host:api.bling.com.br"])

        body = json.loads(mock_post.call_args.kwargs["data"])
        serie = body["series"][0]
        self.assertEqual(serie["metric"], "robo.http.latencia_ms")
        self.assertEqual(serie["type"], 3)
        self.assertEqual(serie["points"][0]["value"], 123.4)

    @patch("core.datadog_metrics.requests.post", side_effect=RuntimeError("rede fora"))
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_excecao_rede_nao_propaga(self, *_):
        datadog_metrics.incrementar("teste.evento")  # não deve lançar

    @patch("core.datadog_metrics.gauge")
    def test_medir_latencia_envia_gauge_em_ms(self, mock_gauge):
        with datadog_metrics.medir_latencia("ml.listar_produtos", tags=["marketplace:mercadolivre"]):
            pass

        mock_gauge.assert_called_once()
        nome, valor = mock_gauge.call_args.args[0], mock_gauge.call_args.args[1]
        self.assertEqual(nome, "ml.listar_produtos.latencia_ms")
        self.assertGreaterEqual(valor, 0)


if __name__ == "__main__":
    unittest.main()
