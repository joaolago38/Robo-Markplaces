"""
tests/test_debug_bling_refresh.py
Cobre persistência dos tokens após refresh bem-sucedido em debug_bling_refresh.py.
"""
import importlib
import os
import sys
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scripts.debug_bling_refresh as mod


def _mock_resp(body: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.content = b"{}"
    r.json.return_value = body
    r.text = str(body)
    return r


class TestHandleRefreshSuccess(unittest.TestCase):
    def setUp(self):
        importlib.reload(mod)

    @patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=False)
    @patch("scripts.debug_bling_refresh.sync_secrets_github", return_value=True)
    def test_sync_automatico_em_actions_nao_imprime_tokens(self, mock_sync):
        saida = StringIO()
        with patch("sys.stdout", saida):
            code = mod._handle_refresh_success("acc_novo", "ref_novo")
        self.assertEqual(code, 0)
        mock_sync.assert_called_once_with("acc_novo", "ref_novo", prefix="BLING")
        out = saida.getvalue()
        self.assertIn("Secrets BLING_* atualizados", out)
        self.assertNotIn("acc_novo", out)
        self.assertNotIn("ref_novo", out)

    @patch.dict(os.environ, {"GITHUB_ACTIONS": ""}, clear=False)
    @patch("scripts.debug_bling_refresh.sync_secrets_github")
    def test_fora_actions_imprime_tokens_destacados(self, mock_sync):
        saida = StringIO()
        with patch("sys.stdout", saida):
            code = mod._handle_refresh_success("acc_local", "ref_local")
        self.assertEqual(code, 0)
        mock_sync.assert_not_called()
        out = saida.getvalue()
        self.assertIn("BLING_ACCESS_TOKEN:  acc_local", out)
        self.assertIn("BLING_REFRESH_TOKEN: ref_local", out)
        self.assertIn("ROTACIONADO", out)

    @patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=False)
    @patch("scripts.debug_bling_refresh.sync_secrets_github", return_value=False)
    def test_sync_falha_cai_no_fallback_com_tokens(self, mock_sync):
        saida = StringIO()
        with patch("sys.stdout", saida):
            code = mod._handle_refresh_success("acc_fb", "ref_fb")
        self.assertEqual(code, 0)
        mock_sync.assert_called_once()
        out = saida.getvalue()
        self.assertIn("sync dos Secrets falhou", out)
        self.assertIn("BLING_ACCESS_TOKEN:  acc_fb", out)
        self.assertIn("BLING_REFRESH_TOKEN: ref_fb", out)


class TestMainRefresh(unittest.TestCase):
    _ENV = {
        "BLING_CLIENT_ID": "cid",
        "BLING_CLIENT_SECRET": "sec",
        "BLING_REFRESH_TOKEN": "ref",
        "GITHUB_ACTIONS": "",
    }

    def setUp(self):
        importlib.reload(mod)

    @patch("scripts.debug_bling_refresh.ref", "ref")
    @patch("scripts.debug_bling_refresh.sec", "sec")
    @patch("scripts.debug_bling_refresh.cid", "cid")
    @patch("scripts.debug_bling_refresh.requests.post")
    def test_main_sucesso_chama_handle(self, mock_post):
        mock_post.return_value = _mock_resp(
            {"access_token": "A", "refresh_token": "R"},
            200,
        )
        with patch.dict(os.environ, self._ENV, clear=False):
            with patch.object(mod, "_handle_refresh_success", return_value=0) as handle:
                code = mod.main()
        self.assertEqual(code, 0)
        handle.assert_called_once_with("A", "R")

    @patch("scripts.debug_bling_refresh.ref", "ref")
    @patch("scripts.debug_bling_refresh.sec", "sec")
    @patch("scripts.debug_bling_refresh.cid", "cid")
    @patch("scripts.debug_bling_refresh.requests.post")
    def test_main_erro_nao_vaza_tokens(self, mock_post):
        mock_post.return_value = _mock_resp(
            {"error": "invalid_grant", "error_description": "Token expired"},
            400,
        )
        saida = StringIO()
        with patch.dict(os.environ, self._ENV, clear=False):
            with patch("sys.stdout", saida):
                code = mod.main()
        self.assertEqual(code, 1)
        out = saida.getvalue()
        self.assertIn("invalid_grant", out)
        self.assertNotIn("BLING_ACCESS_TOKEN:", out)


if __name__ == "__main__":
    unittest.main()
