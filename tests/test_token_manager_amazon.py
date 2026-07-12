"""
tests/test_token_manager_amazon.py
Cobre renovação automática do token LWA da Amazon SP-API.
"""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.config as cfg
import core.token_manager as tm


def _resp(status: int, text: str = "", body: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = body or {}
    r.raise_for_status = MagicMock()
    return r


class TestRenovarTokenAmazon(unittest.TestCase):
    def setUp(self):
        tm._token_cache_amazon["access_token"] = None
        tm._token_cache_amazon["expires_at"] = 0
        tm._amazon_refresh_efetivo["valor"] = "refresh_amz"

    def tearDown(self):
        tm._token_cache_amazon["access_token"] = None
        tm._token_cache_amazon["expires_at"] = 0
        tm._amazon_refresh_efetivo["valor"] = None

    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        AMAZON_LWA_CLIENT_ID="cid",
        AMAZON_LWA_CLIENT_SECRET="sec",
        AMAZON_REFRESH_TOKEN="refresh_amz",
    )
    def test_sucesso_retorna_access_token(self, mock_request):
        mock_request.return_value = _resp(
            200,
            body={"access_token": "acc_amz", "expires_in": 3600, "token_type": "bearer"},
        )
        out = tm._renovar_token_amazon()
        self.assertEqual(out, "acc_amz")
        self.assertEqual(cfg.AMAZON_ACCESS_TOKEN, "acc_amz")

    @patch.object(tm, "log_erros_tokens_ativos", return_value=True)
    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        AMAZON_LWA_CLIENT_ID="cid",
        AMAZON_LWA_CLIENT_SECRET="sec",
        AMAZON_REFRESH_TOKEN="refresh_amz",
    )
    def test_http_401_tratado(self, mock_request, _log_on):
        mock_request.return_value = _resp(401, '{"error":"invalid_grant"}')
        with self.assertLogs("token_manager", level="ERROR") as logs:
            out = tm._renovar_token_amazon()
        self.assertIsNone(out)
        self.assertIn("HTTP 401", logs.output[0])

    @patch.object(tm, "log_erros_tokens_ativos", return_value=True)
    @patch.multiple(
        cfg,
        AMAZON_LWA_CLIENT_ID="",
        AMAZON_LWA_CLIENT_SECRET="",
        AMAZON_REFRESH_TOKEN="",
    )
    def test_sem_credenciais_retorna_none(self, _log_on):
        tm._amazon_refresh_efetivo["valor"] = None
        with self.assertLogs("token_manager", level="ERROR"):
            self.assertIsNone(tm._renovar_token_amazon())

    @patch.object(tm, "_renovar_token_amazon")
    @patch.multiple(
        cfg,
        AMAZON_LWA_CLIENT_ID="cid",
        AMAZON_LWA_CLIENT_SECRET="sec",
        AMAZON_REFRESH_TOKEN="refresh_amz",
        AMAZON_ACCESS_TOKEN="static",
    )
    def test_get_token_amazon_usa_cache(self, mock_renovar):
        tm._token_cache_amazon["access_token"] = "cached"
        tm._token_cache_amazon["expires_at"] = time.time() + 9999
        self.assertEqual(tm.get_token_amazon(), "cached")
        mock_renovar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
