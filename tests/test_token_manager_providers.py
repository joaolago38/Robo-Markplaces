"""
tests/test_token_manager_providers.py — renovação ML/Magalu/Meta/Shopee/Bling.
"""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.config as cfg
import core.token_manager as tm


def _resp(status: int, body: dict | None = None, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text or str(body or "")
    r.json.return_value = body or {}
    r.raise_for_status = MagicMock()
    return r


class TestTokenManagerProviders(unittest.TestCase):
    def setUp(self):
        tm._token_cache_ml.update({"access_token": None, "expires_at": 0})
        tm._token_cache_magalu.update({"access_token": None, "expires_at": 0})
        tm._token_cache_meta.update({"access_token": None, "expires_at": 0})
        tm._token_cache_shopee.update({"access_token": None, "expires_at": 0})
        tm._ml_refresh_efetivo["valor"] = None
        tm._magalu_refresh_efetivo["valor"] = None
        tm._shopee_refresh_efetivo["valor"] = None

    @patch.object(tm, "request")
    @patch.multiple(cfg, ML_CLIENT_ID="id", ML_CLIENT_SECRET="sec", ML_REFRESH_TOKEN="rt")
    def test_ml_refresh_sucesso_rotaciona_refresh(self, mock_request):
        tm._ml_refresh_efetivo["valor"] = "rt"
        mock_request.return_value = _resp(
            200,
            {"access_token": "new_at", "expires_in": 3600, "refresh_token": "new_rt"},
        )
        out = tm._renovar_token_ml()
        self.assertEqual(out, "new_at")
        self.assertEqual(tm._ml_refresh_efetivo["valor"], "new_rt")

    @patch.object(tm, "request")
    @patch.multiple(cfg, ML_CLIENT_ID="id", ML_CLIENT_SECRET="sec", ML_REFRESH_TOKEN="rt")
    def test_ml_refresh_401(self, mock_request):
        tm._ml_refresh_efetivo["valor"] = "rt"
        mock_request.return_value = _resp(401, text="invalid_grant")
        mock_request.return_value.raise_for_status.side_effect = RuntimeError("401")
        with self.assertLogs("token_manager", level="ERROR"):
            self.assertIsNone(tm._renovar_token_ml())

    @patch.object(tm, "request")
    def test_ml_sem_credenciais_nao_chama(self, mock_request):
        with patch.multiple(cfg, ML_CLIENT_ID="", ML_CLIENT_SECRET="", ML_REFRESH_TOKEN=""):
            with self.assertLogs("token_manager", level="ERROR"):
                self.assertIsNone(tm._renovar_token_ml())
        mock_request.assert_not_called()

    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        MAGALU_CLIENT_ID="cid",
        MAGALU_CLIENT_SECRET="sec",
        MAGALU_REFRESH_TOKEN="rt",
    )
    def test_magalu_refresh_sucesso(self, mock_request):
        tm._magalu_refresh_efetivo["valor"] = "rt"
        mock_request.return_value = _resp(
            200,
            {"access_token": "mag_at", "expires_in": 3600, "refresh_token": "mag_rt"},
        )
        out = tm._renovar_token_magalu()
        self.assertEqual(out, "mag_at")

    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        MAGALU_CLIENT_ID="cid",
        MAGALU_CLIENT_SECRET="sec",
        MAGALU_REFRESH_TOKEN="rt",
    )
    def test_magalu_refresh_400(self, mock_request):
        tm._magalu_refresh_efetivo["valor"] = "rt"
        mock_request.return_value = _resp(400, text="bad request")
        with self.assertLogs("token_manager", level="ERROR"):
            self.assertIsNone(tm._renovar_token_magalu())

    @patch.object(tm, "request")
    @patch.multiple(cfg, META_APP_ID="app", META_APP_SECRET="sec", META_ACCESS_TOKEN="long")
    def test_meta_refresh_sucesso(self, mock_request):
        tm._meta_token_efetivo["valor"] = "long"
        mock_request.return_value = _resp(200, {"access_token": "meta_new", "expires_in": 5000})
        out = tm._renovar_token_meta()
        self.assertEqual(out, "meta_new")

    @patch.object(tm, "request")
    @patch.multiple(cfg, META_APP_ID="", META_APP_SECRET="", META_ACCESS_TOKEN="")
    def test_meta_sem_credenciais(self, mock_request):
        tm._meta_token_efetivo["valor"] = None
        with self.assertLogs("token_manager", level="ERROR"):
            self.assertIsNone(tm._renovar_token_meta())
        mock_request.assert_not_called()

    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        SHOPEE_PARTNER_ID="1",
        SHOPEE_PARTNER_KEY="key",
        SHOPEE_SHOP_ID="2",
        SHOPEE_REFRESH_TOKEN="rt",
    )
    def test_shopee_refresh_sucesso(self, mock_request):
        tm._shopee_refresh_efetivo["valor"] = "rt"
        mock_request.return_value = _resp(
            200,
            {"response": {"access_token": "sp_at", "expire_in": 3600, "refresh_token": "sp_rt"}},
        )
        out = tm._renovar_token_shopee()
        self.assertEqual(out, "sp_at")

    @patch.object(tm, "get_token_ml", return_value="cached")
    def test_get_token_ml_usa_cache(self, *_):
        tm._token_cache_ml["access_token"] = "cached"
        tm._token_cache_ml["expires_at"] = time.time() + 9999
        self.assertEqual(tm.get_token_ml(), "cached")

    @patch.object(tm, "_renovar_token_bling", return_value="bling_at")
    def test_get_token_bling_forcar(self, mock_renovar):
        out = tm.get_token_bling(forcar=True)
        self.assertEqual(out, "bling_at")
        mock_renovar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
