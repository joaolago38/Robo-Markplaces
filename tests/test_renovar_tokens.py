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
  RT05: main imprime mensagem do Bling (renovacao manual)
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
from unittest.mock import patch, MagicMock

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
            "MAGALU_CLIENT_ID": "", "MAGALU_CLIENT_SECRET": "", "MAGALU_MERCHANT_ID": "",
        }

    # RT04
    def test_RT04_exit_code_0_sem_credenciais(self):
        with patch.dict(os.environ, self._env_vazio()):
            m = _reload({})
            with patch("builtins.print"):
                resultado = m.main()
        self.assertEqual(resultado, 0)

    # RT05
    def test_RT05_imprime_mensagem_bling_manual(self):
        with patch.dict(os.environ, self._env_vazio()):
            m = _reload({})
            saida = StringIO()
            with patch("sys.stdout", saida):
                m.main()
        self.assertIn("pegar_token_bling", saida.getvalue())

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
            "ML_CLIENT_ID": "cid", "ML_CLIENT_SECRET": "csec", "ML_REFRESH_TOKEN": "ref",
            "SHOPEE_PARTNER_ID": "", "SHOPEE_PARTNER_KEY": "", "SHOPEE_SHOP_ID": "",
            "MAGALU_CLIENT_ID": "", "MAGALU_CLIENT_SECRET": "", "MAGALU_MERCHANT_ID": "",
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
            "ML_CLIENT_ID": "cid", "ML_CLIENT_SECRET": "csec", "ML_REFRESH_TOKEN": "ref",
            "SHOPEE_PARTNER_ID": "", "SHOPEE_PARTNER_KEY": "", "SHOPEE_SHOP_ID": "",
            "MAGALU_CLIENT_ID": "", "MAGALU_CLIENT_SECRET": "", "MAGALU_MERCHANT_ID": "",
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
            "ML_CLIENT_ID": "cid", "ML_CLIENT_SECRET": "csec", "ML_REFRESH_TOKEN": "ref",
            "SHOPEE_PARTNER_ID": "", "SHOPEE_PARTNER_KEY": "", "SHOPEE_SHOP_ID": "",
            "MAGALU_CLIENT_ID": "", "MAGALU_CLIENT_SECRET": "", "MAGALU_MERCHANT_ID": "",
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


if __name__ == "__main__":
    unittest.main()
