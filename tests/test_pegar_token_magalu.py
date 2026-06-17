"""
tests/test_pegar_token_magalu.py
Cobre o bootstrap OAuth do Magalu (authorization_code -> access/refresh token).
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pegar_token_magalu as ptm


def _resp(status: int, body: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


class TestTrocarCodePorToken(unittest.TestCase):
    @patch.object(ptm, "CLIENT_ID", "cid")
    @patch.object(ptm, "CLIENT_SECRET", "sec")
    @patch.object(ptm, "REDIRECT_URI", "https://www.google.com")
    @patch.object(ptm, "requests")
    def test_sucesso_form(self, mock_requests):
        mock_requests.post.return_value = _resp(
            200, {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600}
        )
        resp, dados = ptm.trocar_code_por_token("CODE")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(dados["access_token"], "acc")
        mock_requests.post.assert_called_once()

    @patch.object(ptm, "CLIENT_ID", "cid")
    @patch.object(ptm, "CLIENT_SECRET", "sec")
    @patch.object(ptm, "REDIRECT_URI", "https://www.google.com")
    @patch.object(ptm, "requests")
    def test_retry_json_em_400(self, mock_requests):
        mock_requests.post.side_effect = [
            _resp(400, {"error": "invalid_grant"}),
            _resp(200, {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600}),
        ]
        resp, dados = ptm.trocar_code_por_token("CODE")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(dados["access_token"], "acc")
        self.assertEqual(mock_requests.post.call_count, 2)
        self.assertEqual(mock_requests.post.call_args_list[1][1]["json"]["grant_type"], "authorization_code")

    @patch.object(ptm, "CLIENT_ID", "cid")
    @patch.object(ptm, "CLIENT_SECRET", "sec")
    @patch.object(ptm, "REDIRECT_URI", "https://www.google.com")
    @patch.object(ptm, "requests")
    def test_retry_json_em_415(self, mock_requests):
        mock_requests.post.side_effect = [
            _resp(415, {}),
            _resp(200, {"access_token": "acc", "refresh_token": "ref"}),
        ]
        resp, dados = ptm.trocar_code_por_token("CODE")
        self.assertEqual(dados["access_token"], "acc")
        self.assertEqual(mock_requests.post.call_count, 2)

    @patch.object(ptm, "CLIENT_ID", "cid")
    @patch.object(ptm, "CLIENT_SECRET", "sec")
    @patch.object(ptm, "requests")
    def test_resposta_nao_json(self, mock_requests):
        r = MagicMock()
        r.status_code = 500
        r.json.side_effect = ValueError("not json")
        mock_requests.post.return_value = r
        _resp_obj, dados = ptm.trocar_code_por_token("CODE")
        self.assertEqual(dados, {})


class TestMain(unittest.TestCase):
    @patch.object(ptm, "CLIENT_ID", "")
    @patch.object(ptm, "CLIENT_SECRET", "")
    def test_sem_credenciais(self):
        self.assertEqual(ptm.main([]), 1)

    @patch.object(ptm, "CLIENT_ID", "cid")
    @patch.object(ptm, "CLIENT_SECRET", "sec")
    def test_sem_code(self):
        with patch.dict(os.environ, {"MAGALU_OAUTH_CODE": ""}, clear=False):
            self.assertEqual(ptm.main([]), 1)

    @patch.object(ptm, "CLIENT_ID", "cid")
    @patch.object(ptm, "CLIENT_SECRET", "sec")
    @patch.object(ptm, "trocar_code_por_token", return_value=(_resp(400, {"error": "x"}), {"error": "x"}))
    def test_erro_api(self, *_):
        self.assertEqual(ptm.main(["CODE"]), 1)

    @patch.object(ptm, "CLIENT_ID", "cid")
    @patch.object(ptm, "CLIENT_SECRET", "sec")
    @patch.object(ptm, "trocar_code_por_token")
    def test_sucesso_argv(self, mock_trocar):
        mock_trocar.return_value = (
            _resp(200, {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600}),
            {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600},
        )
        self.assertEqual(ptm.main(["CODE"]), 0)
        mock_trocar.assert_called_once_with("CODE")

    @patch.object(ptm, "CLIENT_ID", "cid")
    @patch.object(ptm, "CLIENT_SECRET", "sec")
    def test_sucesso_env_code(self, *_):
        with patch.dict(os.environ, {"MAGALU_OAUTH_CODE": "ENV_CODE"}, clear=False):
            with patch.object(
                ptm,
                "trocar_code_por_token",
                return_value=(
                    _resp(200, {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600}),
                    {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600},
                ),
            ) as mock_trocar:
                self.assertEqual(ptm.main([]), 0)
                mock_trocar.assert_called_once_with("ENV_CODE")


class TestImportEClic(unittest.TestCase):
    @patch("dotenv.load_dotenv", side_effect=Exception("sem dotenv"))
    def test_carregar_dotenv_ignora_erro(self, *_):
        ptm._carregar_dotenv()

    def test_cli_entrypoint_sem_credenciais(self):
        env = os.environ.copy()
        for k in list(env):
            if k.startswith("MAGALU_"):
                env[k] = ""
        env["MAGALU_CLIENT_ID"] = ""
        env["MAGALU_CLIENT_SECRET"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [sys.executable, str(ROOT / "pegar_token_magalu.py")],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertEqual(r.returncode, 1)
        self.assertIn("MAGALU_CLIENT_ID", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
