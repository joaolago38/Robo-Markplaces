"""
tests/test_token_manager_meta.py
Cobre a renovação do token longo do Meta (fb_exchange_token) e o cofre em disco.
"""
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.config as cfg
import core.token_manager as tm


def _resp(body: dict) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    return r


class TestRenovarTokenMeta(unittest.TestCase):
    def setUp(self):
        tm._token_cache_meta["access_token"] = None
        tm._token_cache_meta["expires_at"] = 0
        tm._meta_token_efetivo["valor"] = None
        self._orig = (cfg.META_APP_ID, cfg.META_APP_SECRET, cfg.META_ACCESS_TOKEN)
        cfg.META_APP_ID = "app"
        cfg.META_APP_SECRET = "secret"
        cfg.META_ACCESS_TOKEN = "token_longo_atual"
        os.environ.pop("META_TOKEN_STORE", None)

    def tearDown(self):
        cfg.META_APP_ID, cfg.META_APP_SECRET, cfg.META_ACCESS_TOKEN = self._orig
        tm._token_cache_meta["access_token"] = None
        tm._token_cache_meta["expires_at"] = 0
        tm._meta_token_efetivo["valor"] = None

    @patch.object(tm, "request")
    def test_renova_ok(self, mock_request):
        mock_request.return_value = _resp({"access_token": "novo_longo", "expires_in": 5184000})
        out = tm._renovar_token_meta()
        self.assertEqual(out, "novo_longo")
        self.assertEqual(tm._meta_token_efetivo["valor"], "novo_longo")
        self.assertEqual(cfg.META_ACCESS_TOKEN, "novo_longo")
        self.assertGreater(tm._token_cache_meta["expires_at"], time.time())

    @patch.object(tm, "request")
    def test_sem_access_token_na_resposta(self, mock_request):
        mock_request.return_value = _resp({"erro": "x"})
        self.assertIsNone(tm._renovar_token_meta())

    def test_sem_credenciais(self):
        cfg.META_APP_ID = ""
        self.assertIsNone(tm._renovar_token_meta())

    @patch.object(tm, "request", side_effect=Exception("HTTP 400"))
    def test_excecao(self, _mock):
        self.assertIsNone(tm._renovar_token_meta())

    @patch.object(tm, "request")
    def test_parse_error(self, mock_request):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.side_effect = ValueError("bad json")
        mock_request.return_value = r
        self.assertIsNone(tm._renovar_token_meta())

    @patch.object(tm, "request")
    def test_expires_in_default(self, mock_request):
        mock_request.return_value = _resp({"access_token": "novo"})  # sem expires_in
        out = tm._renovar_token_meta()
        self.assertEqual(out, "novo")


class TestGetTokenMeta(unittest.TestCase):
    def setUp(self):
        tm._token_cache_meta["access_token"] = None
        tm._token_cache_meta["expires_at"] = 0
        tm._meta_token_efetivo["valor"] = None
        self._orig = cfg.META_ACCESS_TOKEN
        os.environ.pop("META_TOKEN_STORE", None)

    def tearDown(self):
        cfg.META_ACCESS_TOKEN = self._orig
        tm._token_cache_meta["access_token"] = None
        tm._token_cache_meta["expires_at"] = 0
        tm._meta_token_efetivo["valor"] = None

    def test_cache_valido(self):
        tm._token_cache_meta["access_token"] = "cacheado"
        tm._token_cache_meta["expires_at"] = time.time() + 1000
        self.assertEqual(tm.get_token_meta(), "cacheado")

    def test_sem_cache_usa_env(self):
        cfg.META_ACCESS_TOKEN = "do_env"
        self.assertEqual(tm.get_token_meta(), "do_env")

    @patch.object(tm, "_renovar_token_meta", return_value="renovado")
    def test_forcar_renova(self, _mock):
        self.assertEqual(tm.get_token_meta(forcar=True), "renovado")

    @patch.object(tm, "_renovar_token_meta", return_value=None)
    def test_forcar_falha_cai_no_env(self, _mock):
        cfg.META_ACCESS_TOKEN = "fallback"
        self.assertEqual(tm.get_token_meta(forcar=True), "fallback")


class TestRenovarMetaDetalhado(unittest.TestCase):
    def setUp(self):
        tm._token_cache_meta["access_token"] = None
        tm._token_cache_meta["expires_at"] = 0
        tm._meta_token_efetivo["valor"] = None
        self._orig = (cfg.META_APP_ID, cfg.META_APP_SECRET, cfg.META_ACCESS_TOKEN)
        os.environ.pop("META_TOKEN_STORE", None)

    def tearDown(self):
        cfg.META_APP_ID, cfg.META_APP_SECRET, cfg.META_ACCESS_TOKEN = self._orig
        tm._token_cache_meta["access_token"] = None
        tm._token_cache_meta["expires_at"] = 0
        tm._meta_token_efetivo["valor"] = None

    def test_sem_credenciais(self):
        cfg.META_APP_ID = ""
        cfg.META_APP_SECRET = ""
        cfg.META_ACCESS_TOKEN = ""
        out = tm.renovar_token_meta_detalhado()
        self.assertFalse(out["ok"])

    @patch.object(tm, "_renovar_token_meta", return_value=None)
    def test_falha_renovar(self, _mock):
        cfg.META_APP_ID = "a"
        cfg.META_APP_SECRET = "b"
        cfg.META_ACCESS_TOKEN = "c"
        out = tm.renovar_token_meta_detalhado()
        self.assertFalse(out["ok"])

    @patch.object(tm, "_renovar_token_meta", return_value="novo")
    def test_ok(self, _mock):
        cfg.META_APP_ID = "a"
        cfg.META_APP_SECRET = "b"
        cfg.META_ACCESS_TOKEN = "c"
        out = tm.renovar_token_meta_detalhado()
        self.assertTrue(out["ok"])
        self.assertEqual(out["access_token"], "novo")


class TestStoreMeta(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("META_TOKEN_STORE", None)
        tm._token_cache_meta["access_token"] = None
        tm._token_cache_meta["expires_at"] = 0
        tm._meta_token_efetivo["valor"] = None

    def test_store_desativado_sem_env(self):
        os.environ.pop("META_TOKEN_STORE", None)
        self.assertIsNone(tm._meta_store_path())
        self.assertEqual(tm._carregar_store_meta(), {})

    def test_salva_e_carrega(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "meta_token.json")
            os.environ["META_TOKEN_STORE"] = caminho
            tm._salvar_store_meta("tk_disco", time.time() + 999)
            store = tm._carregar_store_meta()
            self.assertEqual(store["access_token"], "tk_disco")

    def test_get_token_hidrata_do_disco(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "meta_token.json")
            os.environ["META_TOKEN_STORE"] = caminho
            tm._salvar_store_meta("tk_disco", time.time() + 9999)
            tm._token_cache_meta["access_token"] = None
            self.assertEqual(tm.get_token_meta(), "tk_disco")


if __name__ == "__main__":
    unittest.main()
