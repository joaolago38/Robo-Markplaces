"""
tests/test_datadog_metrics.py — cliente de métricas customizadas (Metrics API v2).
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import datadog_metrics


class TestDatadogMetrics(unittest.TestCase):
    def setUp(self):
        datadog_metrics.reset_falhas_envio()

    @patch("core.datadog_metrics.requests.post")
    @patch("core.config.DD_API_KEY", "")
    @patch("core.config.DD_METRICS_ENABLED", True)
    def test_sem_api_key_nao_chama_http(self, mock_post, *_):
        datadog_metrics.incrementar("teste.evento")
        mock_post.assert_not_called()

    @patch("core.datadog_metrics.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_METRICS_ENABLED", False)
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_metrics_off_mesmo_com_logs_on(self, mock_post, *_):
        datadog_metrics.incrementar("teste.evento")
        mock_post.assert_not_called()

    @patch("core.datadog_metrics.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_METRICS_ENABLED", True)
    @patch("core.config.DD_LOGS_ENABLED", False)
    @patch("core.config.DD_SITE", "datadoghq.com")
    @patch("core.config.DD_ENV", "production")
    def test_metrics_on_mesmo_com_logs_off(self, mock_post, *_):
        mock_post.return_value = MagicMock(status_code=202)
        datadog_metrics.incrementar("token.renovado", tags=["provider:bling"])
        mock_post.assert_called_once()

    @patch("core.datadog_metrics.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_METRICS_ENABLED", True)
    @patch("core.config.DD_SITE", "datadoghq.com")
    @patch("core.config.DD_ENV", "production")
    def test_incrementar_monta_payload_count(self, mock_post, *_):
        mock_post.return_value = MagicMock(status_code=202)
        datadog_metrics.incrementar("token.renovado", tags=["provider:bling"])

        mock_post.assert_called_once()
        url = mock_post.call_args.args[0]
        self.assertIn("api.datadoghq.com/api/v2/series", url)

        body = json.loads(mock_post.call_args.kwargs["data"])
        serie = body["series"][0]
        self.assertEqual(serie["metric"], "robo.token.renovado")
        self.assertEqual(serie["type"], 1)
        self.assertIn("env:production", serie["tags"])
        self.assertIn("service:robo-markplaces", serie["tags"])
        self.assertIn("provider:bling", serie["tags"])
        self.assertEqual(serie["points"][0]["value"], 1.0)

    @patch("core.datadog_metrics.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_METRICS_ENABLED", True)
    def test_descarta_tags_alta_cardinalidade(self, mock_post, *_):
        mock_post.return_value = MagicMock(status_code=202)
        datadog_metrics.incrementar(
            "repricing.falha_aplicacao",
            tags=["canal:mercadolivre", "sku:SKU1", "novos:3", "falhas:2"],
        )
        body = json.loads(mock_post.call_args.kwargs["data"])
        tags = body["series"][0]["tags"]
        self.assertIn("canal:mercadolivre", tags)
        self.assertFalse(any(t.startswith("sku:") for t in tags))
        self.assertFalse(any(t.startswith("novos:") for t in tags))
        self.assertFalse(any(t.startswith("falhas:") for t in tags))

    def test_tag_produto(self):
        self.assertEqual(datadog_metrics.tag_produto("Kit Impala 24"), "produto:kit-impala-24")
        self.assertIsNone(datadog_metrics.tag_produto("   "))

    @patch("core.datadog_metrics.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_METRICS_ENABLED", True)
    def test_gauge_monta_payload_gauge(self, mock_post, *_):
        mock_post.return_value = MagicMock(status_code=202)
        datadog_metrics.gauge("http.latencia_ms", 123.4, tags=["host:api.bling.com.br"])

        body = json.loads(mock_post.call_args.kwargs["data"])
        serie = body["series"][0]
        self.assertEqual(serie["metric"], "robo.http.latencia_ms")
        self.assertEqual(serie["type"], 3)
        self.assertEqual(serie["points"][0]["value"], 123.4)

    @patch("core.datadog_metrics.requests.post", side_effect=RuntimeError("rede fora"))
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_METRICS_ENABLED", True)
    def test_excecao_rede_nao_propaga(self, *_):
        datadog_metrics.incrementar("teste.evento")  # não deve lançar
        self.assertGreaterEqual(datadog_metrics.falhas_envio(), 1)

    @patch("core.datadog_metrics.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_METRICS_ENABLED", True)
    def test_status_http_erro_conta_falha(self, mock_post, *_):
        mock_post.return_value = MagicMock(status_code=403)
        datadog_metrics.gauge("x", 1.0)
        self.assertGreaterEqual(datadog_metrics.falhas_envio(), 1)

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
