"""
tests/test_renovar_tokens_meta.py
Cobre a seção [Meta] de scripts/renovar_tokens.py.
"""
import importlib
import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.token_manager as tm
import scripts.renovar_tokens as mod

ENV_META = {
    "META_APP_ID": "app",
    "META_APP_SECRET": "sec",
    "META_ACCESS_TOKEN": "tok",
    # zera os outros para o main retornar logo após o bloco Meta
    "ML_CLIENT_ID": "", "ML_CLIENT_SECRET": "", "ML_REFRESH_TOKEN": "",
    "SHOPEE_PARTNER_ID": "", "SHOPEE_PARTNER_KEY": "", "SHOPEE_SHOP_ID": "",
    "MAGALU_CLIENT_ID": "", "MAGALU_CLIENT_SECRET": "", "MAGALU_REFRESH_TOKEN": "",
    "AMAZON_LWA_CLIENT_ID": "", "AMAZON_LWA_CLIENT_SECRET": "", "AMAZON_REFRESH_TOKEN": "",
    "BLING_CLIENT_ID": "", "BLING_CLIENT_SECRET": "", "BLING_REFRESH_TOKEN": "",
    "GITHUB_ACTIONS": "", "BLING_SYNC_GITHUB": "",
}

_RENOVAR_VAZIO = {
    "mercadolivre": {"ok": False},
    "shopee": {"ok": False},
    "magalu": {"ok": False},
    "amazon": {"ok": False},
}


def _main(env: dict, renovar_result=None):
    """Executa main() capturando stdout. Recarrega o módulo ANTES de qualquer patch."""
    if renovar_result is None:
        renovar_result = _RENOVAR_VAZIO
    saida = StringIO()
    with patch.dict(os.environ, env, clear=False):
        with patch("sys.stdout", saida):
            with patch("core.token_manager.renovar_todos_tokens", return_value=renovar_result):
                code = mod.main()
    return code, saida.getvalue()


class TestRenovarMeta(unittest.TestCase):
    def setUp(self):
        # Garante que `mod` está fresco e que patches subsequentes não serão desfeitos.
        importlib.reload(mod)

    def test_sem_credenciais_meta(self):
        env = dict(ENV_META)
        env["META_APP_ID"] = ""
        with patch.object(tm, "renovar_token_meta_detalhado") as fake:
            code, out = _main(env)
        fake.assert_not_called()
        self.assertIn("pegar_token_meta.py", out)
        self.assertEqual(code, 0)

    def test_meta_ok(self):
        with patch.object(tm, "renovar_token_meta_detalhado",
                          return_value={"ok": True, "access_token": "novo"}):
            code, out = _main(dict(ENV_META))
        self.assertIn("meta: ok", out)
        self.assertEqual(code, 0)

    def test_meta_falha(self):
        with patch.object(tm, "renovar_token_meta_detalhado",
                          return_value={"ok": False, "motivo": "expirado"}):
            code, out = _main(dict(ENV_META))
        self.assertIn("meta: falhou", out)
        self.assertEqual(code, 1)

    def test_meta_excecao(self):
        with patch.object(tm, "renovar_token_meta_detalhado", side_effect=Exception("boom")):
            code, out = _main(dict(ENV_META))
        self.assertIn("meta: ERRO", out)
        self.assertEqual(code, 1)

    def test_meta_sync_em_actions(self):
        env = dict(ENV_META)
        env["GITHUB_ACTIONS"] = "true"
        with patch.object(tm, "renovar_token_meta_detalhado",
                          return_value={"ok": True, "access_token": "novo"}), \
             patch.object(mod, "_sync_secrets_github", return_value=True) as sync:
            code, _out = _main(env)
        sync.assert_called_once()
        self.assertEqual(code, 0)

    def test_meta_sync_falha_em_actions(self):
        env = dict(ENV_META)
        env["GITHUB_ACTIONS"] = "true"
        with patch.object(tm, "renovar_token_meta_detalhado",
                          return_value={"ok": True, "access_token": "novo"}), \
             patch.object(mod, "_sync_secrets_github", return_value=False):
            code, _out = _main(env)
        self.assertEqual(code, 1)

    @classmethod
    def tearDownClass(cls):
        importlib.reload(mod)


if __name__ == "__main__":
    unittest.main()
