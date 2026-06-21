"""
tests/test_token_manager_bling.py
Cobre renovação do token Bling e mensagens de erro detalhadas (sem raise_for_status).
"""
import os
import sys
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


class TestRenovarTokenBling(unittest.TestCase):
    def setUp(self):
        tm._token_cache_bling["access_token"] = None
        tm._token_cache_bling["expires_at"] = 0
        tm._bling_refresh_efetivo["valor"] = "refresh_teste"

    def tearDown(self):
        tm._token_cache_bling["access_token"] = None
        tm._token_cache_bling["expires_at"] = 0
        tm._bling_refresh_efetivo["valor"] = None

    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        BLING_CLIENT_ID="cid",
        BLING_CLIENT_SECRET="sec",
        BLING_REFRESH_TOKEN="refresh_teste",
    )
    def test_http_400_loga_detalhe_e_dica_sem_raise_for_status(self, mock_request):
        mock_request.return_value = _resp(
            400,
            '{"error":"invalid_client","error_description":"Client authentication failed"}',
            {"error": "invalid_client", "error_description": "Client authentication failed"},
        )
        with self.assertLogs("token_manager", level="ERROR") as logs:
            out = tm._renovar_token_bling()
        self.assertIsNone(out)
        joined = "\n".join(logs.output)
        self.assertIn("HTTP 400", joined)
        self.assertIn("Client authentication failed", joined)
        self.assertIn("BLING_CLIENT_SECRET", joined)
        self.assertNotIn("400 Client Error", joined)
        mock_request.return_value.raise_for_status.assert_not_called()

    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        BLING_CLIENT_ID="cid",
        BLING_CLIENT_SECRET="",
        BLING_REFRESH_TOKEN="refresh_teste",
    )
    def test_sem_client_secret_nao_chama_oauth(self, mock_request):
        with self.assertLogs("token_manager", level="ERROR") as logs:
            out = tm._renovar_token_bling()
        self.assertIsNone(out)
        mock_request.assert_not_called()
        self.assertIn("Credenciais Bling ausentes", logs.output[0])

    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        BLING_CLIENT_ID="cid",
        BLING_CLIENT_SECRET="sec",
        BLING_REFRESH_TOKEN="refresh_teste",
    )
    def test_refresh_sucesso_rotaciona_tokens(self, mock_request):
        mock_request.return_value = _resp(
            200,
            body={"access_token": "new_at", "expires_in": 3600, "refresh_token": "new_rt"},
        )
        out = tm._renovar_token_bling()
        self.assertEqual(out, "new_at")
        self.assertEqual(tm._bling_refresh_efetivo["valor"], "new_rt")


if __name__ == "__main__":
    unittest.main()
