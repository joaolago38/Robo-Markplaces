"""
tests/test_renovar_tokens.py

Testes de scripts/renovar_tokens.py — versão simplificada.
O script atual tem apenas _tem_credenciais() e main().
Bling foi removido (bloqueia IPs do GitHub Actions).

Behaviors cobertos:
  RT01: _tem_credenciais retorna True quando todas as vars presentes
  RT02: _tem_credenciais retorna False quando alguma var ausente
  RT03: _tem_credenciais retorna False quando var vazia
  RT04: main retorna exit_code 0 quando sem credenciais ML/Shopee/Magalu
  RT05: main imprime mensagem de Bling pausado (renovação automática desativada)
  RT06: main imprime mensagem quando sem credenciais
  RT07: main retorna exit_code 1 quando token_manager falha com credencial real
  RT08: main nao levanta excecao quando token_manager lanca excecao
  RT09: main ignora marketplace sem credencial mesmo com outros configurados
  RT10: _tem_credenciais retorna False quando var tem so espacos
"""
import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib
import scripts.renovar_tokens as mod


def _reload(env: dict):
    """Recarrega o modulo com vars de ambiente mockadas."""
    with patch.dict(os.environ, env, clear=False):
        return importlib.reload(mod)


class TestTemCredenciais(unittest.TestCase):

    # RT01
    def test_RT01_retorna_true_quando_todas_presentes(self):
        with patch.dict(os.environ, {
            "ML_CLIENT_ID":     "cid",
            "ML_CLIENT_SECRET": "csec",
            "ML_REFRESH_TOKEN": "ref",
        }):
            m = _reload({})
            self.assertTrue(m._tem_credenciais(["ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN"]))

    # RT02
    def test_RT02_retorna_false_quando_uma_ausente(self):
        env = {"ML_CLIENT_ID": "cid", "ML_CLIENT_SECRET": "csec"}
        env.pop("ML_REFRESH_TOKEN", None)
        with patch.dict(os.environ, env, clear=False):
            # Remove a var se existir
            os.environ.pop("ML_REFRESH_TOKEN", None)
            m = _reload({})
            self.assertFalse(m._tem_credenciais(["ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN"]))

    # RT03
    def test_RT03_retorna_false_quando_var_vazia(self):
        with patch.dict(os.environ, {
            "ML_CLIENT_ID":     "",
            "ML_CLIENT_SECRET": "csec",
            "ML_REFRESH_TOKEN": "ref",
        }):
            m = _reload({})
            self.assertFalse(m._tem_credenciais(["ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN"]))

    # RT10
    def test_RT10_retorna_false_quando_var_so_espacos(self):
        with patch.dict(os.environ, {
            "ML_CLIENT_ID":     "   ",
            "ML_CLIENT_SECRET": "csec",
            "ML_REFRESH_TOKEN": "ref",
        }):
            m = _reload({})
            self.assertFalse(m._tem_credenciais(["ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN"]))


class TestMain(unittest.TestCase):

    def _env_vazio(self):
        """Ambiente sem nenhuma credencial de marketplace."""
        return {
            "ML_CLIENT_ID": "", "ML_CLIENT_SECRET": "", "ML_REFRESH_TOKEN": "",
            "SHOPEE_PARTNER_ID": "", "SHOPEE_PARTNER_KEY": "", "SHOPEE_SHOP_ID": "",
            "MAGALU_CLIENT_ID": "", "MAGALU_CLIENT_SECRET": "", "MAGALU_REFRESH_TOKEN": "",
            "BLING_CLIENT_ID": "", "BLING_CLIENT_SECRET": "", "BLING_REFRESH_TOKEN": "",
            "META_APP_ID": "", "META_APP_SECRET": "", "META_ACCESS_TOKEN": "",
            "GITHUB_ACTIONS": "", "BLING_SYNC_GITHUB": "",
        }

    # RT04
    def test_RT04_exit_code_0_sem_credenciais(self):
        with patch.dict(os.environ, self._env_vazio()):
            m = _reload({})
            with patch("builtins.print"):
                resultado = m.main()
        self.assertEqual(resultado, 0)

    # RT05
    def test_RT05_imprime_mensagem_bling_pausado(self):
        with patch.dict(os.environ, self._env_vazio()):
            m = _reload({})
            saida = StringIO()
            with patch("sys.stdout", saida):
                m.main()
        self.assertIn("PAUSADO", saida.getvalue())
        self.assertIn("empresa vinculada ao token inativa", saida.getvalue())

    # RT06
    def test_RT06_imprime_sem_credencial_quando_vazio(self):
        with patch.dict(os.environ, self._env_vazio()):
            m = _reload({})
            saida = StringIO()
            with patch("sys.stdout", saida):
                m.main()
        self.assertIn("ignorado", saida.getvalue().lower())

    # RT07
    def test_RT07_exit_code_1_quando_token_manager_falha(self):
        env = {
            **self._env_vazio(),
            "ML_CLIENT_ID": "cid", "ML_CLIENT_SECRET": "csec", "ML_REFRESH_TOKEN": "ref",
        }
        with patch.dict(os.environ, env):
            m = _reload({})
            with patch("core.token_manager.renovar_todos_tokens",
                       return_value={"mercadolivre": {"ok": False, "motivo": "erro"}}):
                with patch("builtins.print"):
                    resultado = m.main()
        self.assertEqual(resultado, 1)

    # RT08
    def test_RT08_nao_levanta_excecao_quando_token_manager_falha(self):
        env = {
            **self._env_vazio(),
            "ML_CLIENT_ID": "cid", "ML_CLIENT_SECRET": "csec", "ML_REFRESH_TOKEN": "ref",
        }
        with patch.dict(os.environ, env):
            m = _reload({})
            with patch("core.token_manager.renovar_todos_tokens", side_effect=RuntimeError("falhou")):
                with patch("builtins.print"):
                    try:
                        resultado = m.main()
                        self.assertEqual(resultado, 1)
                    except Exception as e:
                        self.fail(f"main() levantou excecao inesperada: {e}")

    # RT09
    def test_RT09_ignora_marketplace_sem_credencial(self):
        env = {
            **self._env_vazio(),
            "ML_CLIENT_ID": "cid", "ML_CLIENT_SECRET": "csec", "ML_REFRESH_TOKEN": "ref",
        }
        with patch.dict(os.environ, env):
            m = _reload({})
            mock_result = {
                "mercadolivre": {"ok": True},
                "shopee":       {"ok": False, "motivo": "sem credencial"},
                "magalu":       {"ok": False, "motivo": "sem credencial"},
            }
            saida = StringIO()
            with patch("core.token_manager.renovar_todos_tokens", return_value=mock_result):
                with patch("sys.stdout", saida):
                    resultado = m.main()
        # shopee e magalu ignorados — nao devem causar exit_code 1
        self.assertEqual(resultado, 0)

    def test_RT12_mensagem_falha_renovacao_sem_motivo(self):
        env = {
            **self._env_vazio(),
            "ML_CLIENT_ID": "cid", "ML_CLIENT_SECRET": "csec", "ML_REFRESH_TOKEN": "ref",
        }
        with patch.dict(os.environ, env):
            m = _reload({})
            mock_result = {
                "mercadolivre": {"ok": False},
                "shopee": {"ok": False},
                "magalu": {"ok": False},
            }
            saida = StringIO()
            with patch("core.token_manager.renovar_todos_tokens", return_value=mock_result):
                with patch("sys.stdout", saida):
                    resultado = m.main()
        self.assertEqual(resultado, 1)
        self.assertIn("falhou na renovação — ver erro acima", saida.getvalue())


class TestWriteBackBling(unittest.TestCase):
    """Write-back do Bling quando GITHUB_ACTIONS ou BLING_SYNC_GITHUB."""

    _ENV_BASE = {
        "BLING_CLIENT_ID": "cid",
        "BLING_CLIENT_SECRET": "sec",
        "BLING_REFRESH_TOKEN": "old_ref",
        "ML_CLIENT_ID": "", "ML_CLIENT_SECRET": "", "ML_REFRESH_TOKEN": "",
        "SHOPEE_PARTNER_ID": "", "SHOPEE_PARTNER_KEY": "", "SHOPEE_SHOP_ID": "",
        "MAGALU_CLIENT_ID": "", "MAGALU_CLIENT_SECRET": "", "MAGALU_REFRESH_TOKEN": "",
        "META_APP_ID": "", "META_APP_SECRET": "", "META_ACCESS_TOKEN": "",
        "GITHUB_ACTIONS": "", "BLING_SYNC_GITHUB": "",
    }

    def setUp(self):
        importlib.reload(mod)

    def test_bling_sync_em_actions(self):
        env = dict(self._ENV_BASE)
        env["GITHUB_ACTIONS"] = "true"
        res_bling = {"ok": True, "access_token": "acc_novo", "refresh_token": "ref_novo"}
        with patch.dict(os.environ, env, clear=False):
            with patch("core.token_manager.renovar_token_bling_detalhado", return_value=res_bling), \
                 patch.object(mod, "_sync_secrets_github") as sync, \
                 patch("builtins.print"):
                code = mod.main()
        sync.assert_not_called()
        self.assertEqual(code, 0)

    def test_bling_fora_actions_apenas_imprime(self):
        env = dict(self._ENV_BASE)
        saida = StringIO()
        with patch.dict(os.environ, env, clear=False):
            with patch.object(mod, "_sync_secrets_github") as sync, \
                 patch("sys.stdout", saida):
                code = mod.main()
        sync.assert_not_called()
        out = saida.getvalue()
        self.assertIn("PAUSADO", out)
        self.assertEqual(code, 0)

    def test_bling_sync_falha_em_actions(self):
        """Sync falha dentro de token_manager; renovar_tokens não altera exit_code."""
        env = dict(self._ENV_BASE)
        env["GITHUB_ACTIONS"] = "true"
        res_bling = {"ok": True, "access_token": "acc", "refresh_token": "ref"}
        with patch.dict(os.environ, env, clear=False):
            with patch("core.token_manager.renovar_token_bling_detalhado", return_value=res_bling), \
                 patch.object(mod, "_sync_secrets_github", return_value=False), \
                 patch("builtins.print"):
                code = mod.main()
        self.assertEqual(code, 0)


class TestAlertaTokenTravado(unittest.TestCase):
    """Alerta crítico quando Bling (ou outro provedor) entra em estado travado."""

    _ENV_BLING = {
        "BLING_CLIENT_ID": "cid",
        "BLING_CLIENT_SECRET": "sec",
        "BLING_REFRESH_TOKEN": "old_ref",
        "ML_CLIENT_ID": "", "ML_CLIENT_SECRET": "", "ML_REFRESH_TOKEN": "",
        "SHOPEE_PARTNER_ID": "", "SHOPEE_PARTNER_KEY": "", "SHOPEE_SHOP_ID": "",
        "MAGALU_CLIENT_ID": "", "MAGALU_CLIENT_SECRET": "", "MAGALU_REFRESH_TOKEN": "",
        "META_APP_ID": "", "META_APP_SECRET": "", "META_ACCESS_TOKEN": "",
        "GITHUB_ACTIONS": "", "BLING_SYNC_GITHUB": "",
    }

    def setUp(self):
        importlib.reload(mod)
        mod._provedores_alertados.clear()

    def test_bling_travado_nao_dispara_alerta_enquanto_pausado(self):
        res = {"ok": False, "motivo": "falha ao renovar (refresh expirado/inválido?)"}
        with patch.dict(os.environ, self._ENV_BLING, clear=False):
            with patch("core.token_manager.renovar_token_bling_detalhado", return_value=res), \
                 patch.object(mod, "alertar_critico") as mock_alerta, \
                 patch("builtins.print"):
                code = mod.main()
        self.assertEqual(code, 0)
        mock_alerta.assert_not_called()

    def test_bling_sucesso_nao_dispara_alerta(self):
        res = {"ok": True, "access_token": "acc_novo", "refresh_token": "ref_novo"}
        with patch.dict(os.environ, self._ENV_BLING, clear=False):
            with patch("core.token_manager.renovar_token_bling_detalhado", return_value=res), \
                 patch.object(mod, "alertar_critico") as mock_alerta, \
                 patch("builtins.print"):
                code = mod.main()
        self.assertEqual(code, 0)
        mock_alerta.assert_not_called()

    def test_bling_excecao_nao_dispara_alerta_enquanto_pausado(self):
        with patch.dict(os.environ, self._ENV_BLING, clear=False):
            with patch(
                "core.token_manager.renovar_token_bling_detalhado",
                side_effect=RuntimeError("rede indisponível"),
            ), patch.object(mod, "alertar_critico") as mock_alerta, patch("builtins.print"):
                code = mod.main()
        self.assertEqual(code, 0)
        mock_alerta.assert_not_called()

    def test_bling_invalid_client_nao_dispara_alerta_enquanto_pausado(self):
        res = {"ok": False, "motivo": "invalid_client — Client authentication failed"}
        with patch.dict(os.environ, self._ENV_BLING, clear=False):
            with patch("core.token_manager.renovar_token_bling_detalhado", return_value=res), \
                 patch.object(mod, "alertar_critico") as mock_alerta, \
                 patch("builtins.print"):
                mod.main()
        mock_alerta.assert_not_called()

    def test_ml_travado_dispara_alerta(self):
        env = {
            **self._ENV_BLING,
            "BLING_CLIENT_ID": "", "BLING_CLIENT_SECRET": "", "BLING_REFRESH_TOKEN": "",
            "ML_CLIENT_ID": "cid", "ML_CLIENT_SECRET": "csec", "ML_REFRESH_TOKEN": "ref",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "core.token_manager.renovar_todos_tokens",
                return_value={"mercadolivre": {"ok": False, "motivo": "invalid_grant"}, "shopee": {"ok": False}, "magalu": {"ok": False}},
            ), patch.object(mod, "alertar_critico") as mock_alerta, patch("builtins.print"):
                code = mod.main()
        self.assertEqual(code, 1)
        mock_alerta.assert_called_once()
        self.assertIn("MERCADO LIVRE TRAVADO", mock_alerta.call_args[0][0])

    def test_sanitizar_motivo_mascara_token(self):
        out = mod._sanitizar_motivo("erro refresh_token=abc123secret")
        self.assertIn("***", out)
        self.assertNotIn("abc123secret", out)


class TestWriteBackShopeeMagalu(unittest.TestCase):
    """Write-back de Shopee e Magalu após renovar_todos_tokens."""

    _ENV_SHOPEE = {
        "BLING_CLIENT_ID": "", "BLING_CLIENT_SECRET": "", "BLING_REFRESH_TOKEN": "",
        "ML_CLIENT_ID": "", "ML_CLIENT_SECRET": "", "ML_REFRESH_TOKEN": "",
        "SHOPEE_PARTNER_ID": "1", "SHOPEE_PARTNER_KEY": "key", "SHOPEE_SHOP_ID": "99",
        "MAGALU_CLIENT_ID": "", "MAGALU_CLIENT_SECRET": "", "MAGALU_REFRESH_TOKEN": "",
        "META_APP_ID": "", "META_APP_SECRET": "", "META_ACCESS_TOKEN": "",
        "GITHUB_ACTIONS": "true", "BLING_SYNC_GITHUB": "",
    }

    _ENV_MAGALU = {
        "BLING_CLIENT_ID": "", "BLING_CLIENT_SECRET": "", "BLING_REFRESH_TOKEN": "",
        "ML_CLIENT_ID": "", "ML_CLIENT_SECRET": "", "ML_REFRESH_TOKEN": "",
        "SHOPEE_PARTNER_ID": "", "SHOPEE_PARTNER_KEY": "", "SHOPEE_SHOP_ID": "",
        "MAGALU_CLIENT_ID": "cid", "MAGALU_CLIENT_SECRET": "sec", "MAGALU_REFRESH_TOKEN": "ref",
        "META_APP_ID": "", "META_APP_SECRET": "", "META_ACCESS_TOKEN": "",
        "GITHUB_ACTIONS": "true", "BLING_SYNC_GITHUB": "",
    }

    def setUp(self):
        importlib.reload(mod)

    def test_shopee_sync_em_actions(self):
        with patch.dict(os.environ, self._ENV_SHOPEE, clear=False):
            with patch("core.token_manager.renovar_todos_tokens",
                       return_value={"mercadolivre": {"ok": False}, "shopee": {"ok": True}, "magalu": {"ok": False}}), \
                 patch("core.token_manager.tokens_shopee_atuais",
                       return_value={"access_token": "sp_acc", "refresh_token": "sp_ref"}), \
                 patch.object(mod, "_sync_secrets_github", return_value=True) as sync, \
                 patch("builtins.print"):
                code = mod.main()
        sync.assert_called_once_with("sp_acc", "sp_ref", prefix="SHOPEE")
        self.assertEqual(code, 0)

    def test_magalu_sync_em_actions(self):
        with patch.dict(os.environ, self._ENV_MAGALU, clear=False):
            with patch("core.token_manager.renovar_todos_tokens",
                       return_value={"mercadolivre": {"ok": False}, "shopee": {"ok": False}, "magalu": {"ok": True}}), \
                 patch("core.token_manager.tokens_magalu_atuais",
                       return_value={"access_token": "mg_acc", "refresh_token": "mg_ref"}), \
                 patch.object(mod, "_sync_secrets_github", return_value=True) as sync, \
                 patch("builtins.print"):
                code = mod.main()
        sync.assert_called_once_with("mg_acc", "mg_ref", prefix="MAGALU")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
