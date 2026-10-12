"""
tests/test_telegram_gate.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import telegram_gate as tg


class TestTelegramGate(unittest.TestCase):
    def setUp(self):
        tg.reset()

    def test_formato_valido(self):
        self.assertTrue(tg.token_formato_valido("123456:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"))

    def test_formato_invalido(self):
        self.assertFalse(tg.token_formato_valido("token-errado"))

    @patch("core.telegram_gate.request")
    @patch("core.telegram_gate.TELEGRAM_TOKEN", "123:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    def test_verificar_ok(self, mock_request):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"ok": True, "result": {"username": "bot"}}
        r.raise_for_status = MagicMock()
        mock_request.return_value = r
        self.assertTrue(tg.verificar_token(forcar=True))

    @patch("core.telegram_gate.request")
    @patch("core.telegram_gate.TELEGRAM_TOKEN", "123:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    def test_circuit_breaker_apos_404(self, mock_request):
        r = MagicMock()
        r.status_code = 404
        mock_request.return_value = r
        self.assertFalse(tg.verificar_token(forcar=True))
        self.assertFalse(tg.pode_enviar())
        tg.registrar_falha_envio("404 Not Found")
        self.assertFalse(tg.pode_enviar())


if __name__ == "__main__":
    unittest.main()
