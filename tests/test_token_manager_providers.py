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

    @patch.object(tm, "get_token_ml", return_value="ml")
    @patch.object(tm, "get_token_shopee", return_value="sp")
    @patch.object(tm, "get_token_magalu", return_value="mg")
    @patch.object(tm, "get_token_bling", return_value="bl")
    def test_garantir_tokens_marketplaces(self, *_):
        out = tm.garantir_tokens_marketplaces()
        self.assertTrue(all(out.values()))

    @patch.object(tm, "_renovar_token_ml", return_value="ml")
    @patch.object(tm, "_renovar_token_shopee", return_value="sp")
    @patch.object(tm, "_renovar_token_magalu", return_value="mg")
    def test_renovar_todos_tokens(self, *_):
        out = tm.renovar_todos_tokens()
        self.assertTrue(out["mercadolivre"]["ok"])

    @patch.object(tm, "_renovar_token_bling", return_value=None)
    @patch.multiple(cfg, BLING_CLIENT_ID="c", BLING_CLIENT_SECRET="s", BLING_REFRESH_TOKEN="r")
    def test_renovar_token_bling_detalhado_falha(self, *_):
        tm._bling_refresh_efetivo["valor"] = "r"
        out = tm.renovar_token_bling_detalhado()
        self.assertFalse(out["ok"])

    @patch.object(tm, "_renovar_token_bling", return_value="at")
    @patch.multiple(cfg, BLING_CLIENT_ID="c", BLING_CLIENT_SECRET="s", BLING_REFRESH_TOKEN="r")
    def test_renovar_token_bling_detalhado_ok(self, *_):
        tm._bling_refresh_efetivo["valor"] = "r"
        out = tm.renovar_token_bling_detalhado()
        self.assertTrue(out["ok"])
        self.assertEqual(out["access_token"], "at")

    @patch.object(tm, "get_token_ml", return_value="cached")
    def test_tokens_ml_atuais(self, *_):
        tm._token_cache_ml["access_token"] = "cached"
        tm._ml_refresh_efetivo["valor"] = "rt"
        out = tm.tokens_ml_atuais()
        self.assertEqual(out["access_token"], "cached")
        self.assertEqual(out["refresh_token"], "rt")



    @patch.object(tm, "_meta_token_disponivel", return_value=None)
    def test_renovar_token_meta_detalhado_sem_cred(self, *_):
        out = tm.renovar_token_meta_detalhado()
        self.assertFalse(out["ok"])

    def test_tokens_shopee_e_magalu_atuais(self):
        tm._token_cache_shopee["access_token"] = "sp_at"
        tm._shopee_refresh_efetivo["valor"] = "sp_rt"
        tm._token_cache_magalu["access_token"] = "mg_at"
        tm._magalu_refresh_efetivo["valor"] = "mg_rt"
        self.assertEqual(tm.tokens_shopee_atuais()["access_token"], "sp_at")
        self.assertEqual(tm.tokens_magalu_atuais()["refresh_token"], "mg_rt")

    @patch.object(tm, "request")
    @patch.multiple(cfg, SHOPEE_PARTNER_ID="1", SHOPEE_PARTNER_KEY="k", SHOPEE_SHOP_ID="2", SHOPEE_REFRESH_TOKEN="")
    def test_get_token_shopee_sem_refresh_retorna_env(self, *_):
        with patch.object(cfg, "SHOPEE_ACCESS_TOKEN", "static"):
            self.assertEqual(tm.get_token_shopee(), "static")

    @patch.object(tm, "request")
    @patch.multiple(cfg, BLING_CLIENT_ID="cid", BLING_CLIENT_SECRET="sec", BLING_REFRESH_TOKEN="rt")
    def test_bling_refresh_401_dica(self, mock_request):
        tm._bling_refresh_efetivo["valor"] = "rt"
        mock_request.return_value = _resp(
            401,
            body={"error": "invalid_client", "error_description": "invalid client"},
        )
        with self.assertLogs("token_manager", level="ERROR") as logs:
            self.assertIsNone(tm._renovar_token_bling())
        self.assertTrue(any("BLING_CLIENT" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
