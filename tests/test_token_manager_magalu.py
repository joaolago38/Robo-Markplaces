"""
tests/test_token_manager_magalu.py
Cobre diagnóstico de erro HTTP na renovação do token Magalu.
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


class TestRenovarTokenMagalu(unittest.TestCase):
    def setUp(self):
        tm._token_cache_magalu["access_token"] = None
        tm._token_cache_magalu["expires_at"] = 0
        tm._magalu_refresh_efetivo["valor"] = "refresh_teste"

    def tearDown(self):
        tm._token_cache_magalu["access_token"] = None
        tm._token_cache_magalu["expires_at"] = 0
        tm._magalu_refresh_efetivo["valor"] = None

    @patch.object(tm, "log_erros_tokens_ativos", return_value=True)
    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        MAGALU_CLIENT_ID="cid",
        MAGALU_CLIENT_SECRET="sec",
        MAGALU_REFRESH_TOKEN="refresh_teste",
    )
    def test_http_400_loga_corpo_e_retorna_none(self, mock_request, _log_on):
        mock_request.return_value = _resp(400, '{"error":"invalid_grant"}')
        with self.assertLogs("token_manager", level="ERROR") as logs:
            out = tm._renovar_token_magalu()
        self.assertIsNone(out)
        self.assertIn("HTTP 400", logs.output[0])
        self.assertIn("invalid_grant", logs.output[0])
        mock_request.return_value.raise_for_status.assert_not_called()

    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        MAGALU_CLIENT_ID="cid",
        MAGALU_CLIENT_SECRET="sec",
        MAGALU_REFRESH_TOKEN="refresh_teste",
    )
    def test_sucesso_retorna_access_token(self, mock_request):
        mock_request.return_value = _resp(
            200,
            body={
                "access_token": "acc_magalu",
                "expires_in": 3600,
                "refresh_token": "ref_novo",
            },
        )
        out = tm._renovar_token_magalu()
        self.assertEqual(out, "acc_magalu")
        self.assertEqual(tm._magalu_refresh_efetivo["valor"], "ref_novo")

    @patch.object(tm, "log_erros_tokens_ativos", return_value=True)
    @patch.object(tm, "request", side_effect=ConnectionError("rede"))
    @patch.multiple(
        cfg,
        MAGALU_CLIENT_ID="cid",
        MAGALU_CLIENT_SECRET="sec",
        MAGALU_REFRESH_TOKEN="refresh_teste",
    )
    def test_erro_rede_loga_excecao(self, *_):
        with self.assertLogs("token_manager", level="ERROR") as logs:
            out = tm._renovar_token_magalu()
        self.assertIsNone(out)
        self.assertIn("rede/parse", logs.output[0])
        self.assertIn("rede", logs.output[0])

    @patch.multiple(
        cfg,
        MAGALU_CLIENT_ID="",
        MAGALU_CLIENT_SECRET="",
        MAGALU_REFRESH_TOKEN="",
    )
    def test_sem_credenciais_retorna_none(self):
        tm._magalu_refresh_efetivo["valor"] = None
        self.assertIsNone(tm._renovar_token_magalu())

    @patch.object(tm, "_magalu_canal_operando", return_value=False)
    @patch.object(tm, "_renovar_token_magalu")
    def test_get_token_magalu_nao_renova_canal_inativo(self, mock_renovar, _):
        self.assertIsNone(tm.get_token_magalu())
        mock_renovar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
