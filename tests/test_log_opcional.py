"""
tests/test_log_opcional.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import log_opcional as lo
from core import http_client
from core import claude_client


class TestLogOpcional(unittest.TestCase):
    def test_erro_opcional_debug_quando_off(self):
        log = MagicMock()
        lo.erro_opcional(log, False, "falhou %s", "x", flag_hint="LOG_ERROS_BLING")
        log.debug.assert_called_once()
        self.assertIn("LOG_ERROS_BLING=1", log.debug.call_args.args[0])
        log.error.assert_not_called()

    def test_erro_opcional_error_quando_on(self):
        log = MagicMock()
        lo.erro_opcional(log, True, "falhou %s", "x", flag_hint="LOG_ERROS_BLING")
        log.error.assert_called_once()
        log.debug.assert_not_called()

    def test_host_scraper_leopardo(self):
        self.assertTrue(lo.host_scraper_veiculos("www.leopardoveiculos.com.br"))
        self.assertTrue(lo.host_scraper_veiculos("www.veiculosbatidos.com.br"))
        self.assertFalse(lo.host_scraper_veiculos("api.mercadolibre.com"))

    @patch.object(lo, "log_erros_veiculos_ativos", return_value=False)
    @patch("core.http_client.incrementar")
    @patch("core.http_client.gauge")
    @patch("core.http_client._SESSION.request", side_effect=RuntimeError("pool"))
    def test_http_scraper_nao_loga_error(self, *_mocks):
        with patch.object(http_client.logger, "error") as mock_err, patch.object(
            http_client.logger, "debug"
        ) as mock_dbg:
            with self.assertRaises(RuntimeError):
                http_client.request("GET", "https://www.leopardoveiculos.com.br/veiculos")
            mock_err.assert_not_called()
            mock_dbg.assert_called()

    @patch.object(lo, "log_erros_claude_ativos", return_value=False)
    def test_claude_erro_vira_debug(self, _):
        with patch.object(claude_client.logger, "error") as mock_err, patch.object(
            claude_client.logger, "debug"
        ) as mock_dbg:
            claude_client._log_erro_claude(Exception("400 Bad Request"), contexto="texto livre")
            mock_err.assert_not_called()
            mock_dbg.assert_called()


if __name__ == "__main__":
    unittest.main()
