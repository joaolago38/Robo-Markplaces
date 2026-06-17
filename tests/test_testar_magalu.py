"""
tests/test_testar_magalu.py
Cobre o diagnóstico de renovação do token Magalu (sem rede real).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import testar_magalu as tm


def _post_resp(status: int, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


class TestCarregarCredenciais(unittest.TestCase):
    def test_lê_e_strip(self):
        env = {
            "MAGALU_CLIENT_ID": "  cid  ",
            "MAGALU_CLIENT_SECRET": " sec ",
            "MAGALU_REFRESH_TOKEN": " ref ",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.object(tm, "_carregar_dotenv"):
                out = tm.carregar_credenciais()
        self.assertEqual(out["client_id"], "cid")
        self.assertEqual(out["client_secret"], "sec")
        self.assertEqual(out["refresh_token"], "ref")


class TestCarregarDotenv(unittest.TestCase):
    @patch("dotenv.load_dotenv")
    def test_load_dotenv_chamado(self, mock_ld):
        tm._carregar_dotenv()
        mock_ld.assert_called_once()

    @patch("dotenv.load_dotenv", side_effect=Exception("sem dotenv"))
    def test_load_dotenv_falha_ignorada(self, *_):
        tm._carregar_dotenv()


class TestMascarar(unittest.TestCase):
    def test_nao_vaza_valor_completo(self):
        valor = "abcdefghijklmnop"
        out = tm.mascarar(valor)
        self.assertNotIn(valor, out)
        self.assertIn("tam=16", out)

    def test_vazio(self):
        self.assertEqual(tm.mascarar(""), "(vazio)")

    def test_curto(self):
        out = tm.mascarar("abc")
        self.assertIn("****", out)
        self.assertNotIn("abc", out)


class TestRenovar(unittest.TestCase):
    @patch.object(tm, "requests")
    def test_sucesso_200(self, mock_requests):
        mock_requests.post.return_value = _post_resp(200, '{"access_token":"acc"}')
        status, corpo = tm.renovar("cid", "sec", "ref")
        self.assertEqual(status, 200)
        self.assertIn("access_token", corpo)
        mock_requests.post.assert_called_once()

    @patch.object(tm, "requests")
    def test_erro_400_propaga_corpo(self, mock_requests):
        corpo_erro = '{"error":"invalid_grant"}'
        mock_requests.post.return_value = _post_resp(400, corpo_erro)
        status, corpo = tm.renovar("cid", "sec", "ref")
        self.assertEqual(status, 400)
        self.assertEqual(corpo, corpo_erro)


class TestMain(unittest.TestCase):
    def _env_ok(self):
        return {
            "MAGALU_CLIENT_ID": "cid",
            "MAGALU_CLIENT_SECRET": "sec",
            "MAGALU_REFRESH_TOKEN": "ref",
        }

    @patch.object(tm, "renovar", return_value=(200, '{"access_token":"acc"}'))
    @patch.object(tm, "_carregar_dotenv")
    def test_main_sucesso_retorna_0(self, *_):
        with patch.dict(os.environ, self._env_ok(), clear=False):
            self.assertEqual(tm.main(), 0)

    @patch.object(tm, "renovar", return_value=(400, '{"error":"invalid_grant"}'))
    @patch.object(tm, "_carregar_dotenv")
    def test_main_400_retorna_1_e_imprime_corpo(self, *_):
        import io

        buf = io.StringIO()
        with patch.dict(os.environ, self._env_ok(), clear=False):
            with patch("sys.stdout", buf):
                code = tm.main()
        self.assertEqual(code, 1)
        self.assertIn("invalid_grant", buf.getvalue())

    @patch.object(tm, "requests")
    @patch.object(tm, "_carregar_dotenv")
    def test_main_sem_credencial_nao_chama_http(self, _dotenv, mock_requests):
        env = self._env_ok()
        env["MAGALU_REFRESH_TOKEN"] = ""
        with patch.dict(os.environ, env, clear=False):
            code = tm.main()
        self.assertNotEqual(code, 0)
        mock_requests.post.assert_not_called()


class TestCliEntrypoint(unittest.TestCase):
    def test_main_guard_sem_credenciais(self):
        import subprocess
        import tempfile
        from pathlib import Path

        env = os.environ.copy()
        for k in list(env):
            if k.startswith("MAGALU_"):
                env[k] = ""
        env["MAGALU_CLIENT_ID"] = ""
        env["MAGALU_CLIENT_SECRET"] = ""
        env["MAGALU_REFRESH_TOKEN"] = ""
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [sys.executable, str(root / "testar_magalu.py")],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
