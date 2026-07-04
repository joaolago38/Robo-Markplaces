"""
tests/test_preflight_monitor_telegram.py
"""
import importlib.util
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "preflight_monitor_telegram",
    os.path.join(ROOT, "scripts", "preflight_monitor_telegram.py"),
)
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)


class TestPreflightMonitorTelegram(unittest.TestCase):
    @patch("core.config.TELEGRAM_TOKEN", "")
    @patch("core.config.TELEGRAM_GESTOR_CHAT_ID", "123")
    def test_falha_sem_token(self):
        self.assertEqual(preflight.main(), 1)

    @patch("core.config.TELEGRAM_TOKEN", "tok")
    @patch("core.config.TELEGRAM_GESTOR_CHAT_ID", "")
    def test_falha_sem_gestor(self):
        self.assertEqual(preflight.main(), 1)

    @patch("core.http_client.request")
    @patch("core.config.TELEGRAM_TOKEN", "tok")
    @patch("core.config.TELEGRAM_GESTOR_CHAT_ID", "99")
    def test_ok_getme(self, mock_request):
        resp = MagicMock()
        resp.json.return_value = {"ok": True, "result": {"username": "meubot"}}
        mock_request.return_value = resp
        self.assertEqual(preflight.main(), 0)

    @patch("core.http_client.request", side_effect=RuntimeError("404"))
    @patch("core.config.TELEGRAM_TOKEN", "tok")
    @patch("core.config.TELEGRAM_GESTOR_CHAT_ID", "99")
    def test_falha_getme(self, *_):
        self.assertEqual(preflight.main(), 1)


if __name__ == "__main__":
    unittest.main()
