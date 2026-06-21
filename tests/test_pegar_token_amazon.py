"""
tests/test_pegar_token_amazon.py
Cobre o bootstrap OAuth da Amazon SP-API (authorization_code -> access/refresh token).
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

import pegar_token_amazon as pta


def _resp(status: int, body: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


class TestTrocarCodePorToken(unittest.TestCase):
    @patch.object(pta, "CLIENT_ID", "amzn.cid")
    @patch.object(pta, "CLIENT_SECRET", "sec")
    @patch.object(pta, "REDIRECT_URI", "https://www.google.com")
    @patch.object(pta, "requests")
    def test_sucesso_lwa(self, mock_requests):
        mock_requests.post.return_value = _resp(
            200,
            {
                "access_token": "acc",
                "refresh_token": "ref",
                "expires_in": 7200,
            },
        )
        resp, dados = pta.trocar_code_por_token("CODE")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(dados["access_token"], "acc")
        mock_requests.post.assert_called_once()
        payload = mock_requests.post.call_args[1]["data"]
        self.assertEqual(payload["grant_type"], "authorization_code")
        self.assertEqual(payload["redirect_uri"], "https://www.google.com")
        self.assertEqual(payload["client_id"], "amzn.cid")

    @patch.object(pta, "CLIENT_ID", "amzn.cid")
    @patch.object(pta, "CLIENT_SECRET", "sec")
    @patch.object(pta, "requests")
    def test_resposta_nao_json(self, mock_requests):
        r = MagicMock()
        r.status_code = 500
        r.json.side_effect = ValueError("not json")
        mock_requests.post.return_value = r
        _resp_obj, dados = pta.trocar_code_por_token("CODE")
        self.assertEqual(dados, {})


class TestMain(unittest.TestCase):
    @patch.object(pta, "CLIENT_ID", "")
    @patch.object(pta, "CLIENT_SECRET", "")
    def test_sem_credenciais(self):
        self.assertEqual(pta.main([]), 1)

    @patch.object(pta, "CLIENT_ID", "cid")
    @patch.object(pta, "CLIENT_SECRET", "sec")
    def test_sem_code(self):
        with patch.dict(os.environ, {"AMAZON_OAUTH_CODE": ""}, clear=False):
            self.assertEqual(pta.main([]), 1)

    @patch.object(pta, "CLIENT_ID", "cid")
    @patch.object(pta, "CLIENT_SECRET", "sec")
    @patch.object(pta, "trocar_code_por_token", return_value=(_resp(400, {"error": "x"}), {"error": "x"}))
    def test_erro_api(self, *_):
        self.assertEqual(pta.main(["CODE"]), 1)

    @patch.object(pta, "CLIENT_ID", "cid")
    @patch.object(pta, "CLIENT_SECRET", "sec")
    @patch.object(pta, "trocar_code_por_token")
    def test_sucesso_argv(self, mock_trocar):
        mock_trocar.return_value = (
            _resp(200, {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600}),
            {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600},
        )
        self.assertEqual(pta.main(["CODE"]), 0)
        mock_trocar.assert_called_once_with("CODE")

    @patch.object(pta, "CLIENT_ID", "cid")
    @patch.object(pta, "CLIENT_SECRET", "sec")
    def test_sucesso_env_code(self, *_):
        with patch.dict(os.environ, {"AMAZON_OAUTH_CODE": "ENV_CODE"}, clear=False):
            with patch.object(
                pta,
                "trocar_code_por_token",
                return_value=(
                    _resp(200, {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600}),
                    {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600},
                ),
            ) as mock_trocar:
                self.assertEqual(pta.main([]), 0)
                mock_trocar.assert_called_once_with("ENV_CODE")


class TestImportEClic(unittest.TestCase):
    @patch("dotenv.load_dotenv", side_effect=Exception("sem dotenv"))
    def test_carregar_dotenv_ignora_erro(self, *_):
        pta._carregar_dotenv()

    def test_cli_entrypoint_sem_credenciais(self):
        env = os.environ.copy()
        for k in list(env):
            if k.startswith("AMAZON_"):
                env[k] = ""
        env["AMAZON_LWA_CLIENT_ID"] = ""
        env["AMAZON_LWA_CLIENT_SECRET"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [sys.executable, str(ROOT / "pegar_token_amazon.py")],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        self.assertEqual(r.returncode, 1)
        self.assertIn("AMAZON_LWA_CLIENT_ID", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
