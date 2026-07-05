"""
tests/test_preflight_producao.py
"""
import importlib.util
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "preflight_producao",
    os.path.join(ROOT, "scripts", "preflight_producao.py"),
)
preflight_prod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight_prod)


class TestPreflightProducao(unittest.TestCase):
    @patch("scripts.preflight_monitor_telegram.main", return_value=1)
    def test_para_se_telegram_falhar(self, _):
        self.assertEqual(preflight_prod.main(), 1)

    @patch("core.token_manager.get_token_ml", return_value="tok-ml")
    @patch("core.config.ML_REFRESH_TOKEN", "ref")
    @patch("core.config.ML_CLIENT_ID", "cid")
    @patch("scripts.preflight_monitor_telegram.main", return_value=0)
    def test_ok_com_ml(self, *_):
        self.assertEqual(preflight_prod.main(), 0)


if __name__ == "__main__":
    unittest.main()
