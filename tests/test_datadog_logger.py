"""
tests/test_datadog_logger.py — handler Datadog Log Management.
"""
import json
import logging
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.datadog_logger import DatadogLogHandler, configurar_logging_datadog


def _make_record(name: str = "bling_client", msg: str = "evento teste") -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


class TestDatadogLogHandler(unittest.TestCase):
    @patch("core.datadog_logger.requests.post")
    @patch("core.config.DD_API_KEY", "")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_sem_api_key_nao_chama_http(self, mock_post, *_):
        handler = DatadogLogHandler()
        handler.emit(_make_record())
        mock_post.assert_not_called()

    @patch("core.datadog_logger.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    @patch("core.config.DD_SITE", "datadoghq.com")
    def test_emit_bling_client_tag_marketplace(self, mock_post, *_):
        handler = DatadogLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record(name="bling_client", msg="NF-e ok"))

        mock_post.assert_called_once()
        kwargs = mock_post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["DD-API-KEY"], "dd-key-test")
        self.assertIn("http-intake.logs.datadoghq.com/api/v2/logs", mock_post.call_args.args[0])

        payload = json.loads(kwargs["data"])
        self.assertEqual(payload[0]["service"], "robo-markplaces")
        self.assertEqual(payload[0]["message"], "NF-e ok")
        self.assertIn("marketplace:bling", payload[0]["ddtags"])
        self.assertIn("logger:bling_client", payload[0]["ddtags"])
        self.assertIn("level:info", payload[0]["ddtags"])

    @patch("core.datadog_logger.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    @patch("core.config.DD_SITE", "datadoghq.com")
    def test_emit_ml_client_tag_mercadolivre(self, mock_post, *_):
        handler = DatadogLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record(name="ml_client", msg="estoque ok"))

        payload = json.loads(mock_post.call_args.kwargs["data"])
        self.assertIn("marketplace:mercadolivre", payload[0]["ddtags"])

    @patch("core.datadog_logger.requests.post", side_effect=RuntimeError("rede fora"))
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_emit_excecao_rede_nao_propaga(self, *_):
        handler = DatadogLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_make_record())

    @patch("core.datadog_logger.requests.post")
    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_emit_ignora_debug(self, mock_post, *_):
        handler = DatadogLogHandler()
        record = _make_record()
        record.levelno = logging.DEBUG
        record.levelname = "DEBUG"
        handler.emit(record)
        mock_post.assert_not_called()


class TestConfigurarLoggingDatadog(unittest.TestCase):
    def setUp(self):
        self._root = logging.getLogger()
        self._handlers_originais = list(self._root.handlers)

    def tearDown(self):
        self._root.handlers = self._handlers_originais

    @patch("core.config.DD_API_KEY", "dd-key-test")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_idempotente_nao_duplica_handler(self, *_):
        configurar_logging_datadog()
        configurar_logging_datadog()
        handlers = [h for h in self._root.handlers if isinstance(h, DatadogLogHandler)]
        self.assertEqual(len(handlers), 1)

    @patch("core.config.DD_API_KEY", "")
    @patch("core.config.DD_LOGS_ENABLED", True)
    def test_sem_api_key_nao_anexa_handler(self, *_):
        antes = len(self._root.handlers)
        configurar_logging_datadog()
        self.assertEqual(len(self._root.handlers), antes)


if __name__ == "__main__":
    unittest.main()
