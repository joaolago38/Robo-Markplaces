"""
tests/test_pegar_token_meta.py
Cobre o bootstrap OAuth do Meta (code -> token curto -> token longo).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pegar_token_meta as ptm


def _resp(body: dict) -> MagicMock:
    r = MagicMock()
    r.json.return_value = body
    return r


class TestUrlAutorizacao(unittest.TestCase):
    @patch.object(ptm, "APP_ID", "123")
    def test_contem_client_id_e_scope(self, *_):
        url = ptm.url_autorizacao()
        self.assertIn("client_id=123", url)
        self.assertIn("ads_read", url)
        self.assertIn("response_type=code", url)


class TestTrocas(unittest.TestCase):
    @patch.object(ptm, "requests")
    def test_trocar_code(self, mock_requests):
        mock_requests.get.return_value = _resp({"access_token": "curto"})
        out = ptm.trocar_code_por_token("CODE")
        self.assertEqual(out["access_token"], "curto")

    @patch.object(ptm, "requests")
    def test_trocar_longa(self, mock_requests):
        mock_requests.get.return_value = _resp({"access_token": "longo", "expires_in": 5184000})
        out = ptm.trocar_por_longa_duracao("curto")
        self.assertEqual(out["access_token"], "longo")

    @patch.object(ptm, "requests")
    def test_listar_contas(self, mock_requests):
        mock_requests.get.return_value = _resp({"data": [{"account_id": "1", "name": "Conta"}]})
        out = ptm.listar_contas_anuncio("tok")
        self.assertEqual(out[0]["account_id"], "1")

    @patch.object(ptm, "requests")
    def test_listar_contas_excecao(self, mock_requests):
        mock_requests.get.side_effect = Exception("boom")
        self.assertEqual(ptm.listar_contas_anuncio("tok"), [])


class TestMain(unittest.TestCase):
    @patch.object(ptm, "APP_ID", "")
    @patch.object(ptm, "APP_SECRET", "")
    def test_sem_credenciais(self, *_):
        self.assertEqual(ptm.main([]), 1)

    @patch.object(ptm, "APP_ID", "app")
    @patch.object(ptm, "APP_SECRET", "sec")
    def test_url_flag(self, *_):
        self.assertEqual(ptm.main(["--url"]), 0)

    @patch.object(ptm, "APP_ID", "app")
    @patch.object(ptm, "APP_SECRET", "sec")
    def test_sem_code(self, *_):
        with patch.dict(os.environ, {"META_OAUTH_CODE": ""}):
            self.assertEqual(ptm.main([]), 1)

    @patch.object(ptm, "APP_ID", "app")
    @patch.object(ptm, "APP_SECRET", "sec")
    @patch.object(ptm, "trocar_code_por_token", return_value={})
    def test_token_curto_falha(self, *_):
        self.assertEqual(ptm.main(["CODE"]), 1)

    @patch.object(ptm, "APP_ID", "app")
    @patch.object(ptm, "APP_SECRET", "sec")
    @patch.object(ptm, "trocar_code_por_token", return_value={"access_token": "curto"})
    @patch.object(ptm, "trocar_por_longa_duracao", return_value={})
    def test_token_longo_falha(self, *_):
        self.assertEqual(ptm.main(["CODE"]), 1)

    @patch.object(ptm, "APP_ID", "app")
    @patch.object(ptm, "APP_SECRET", "sec")
    @patch.object(ptm, "trocar_code_por_token", return_value={"access_token": "curto"})
    @patch.object(ptm, "trocar_por_longa_duracao", return_value={"access_token": "longo", "expires_in": 1})
    @patch.object(ptm, "listar_contas_anuncio", return_value=[{"account_id": "1", "name": "C", "currency": "BRL"}])
    def test_sucesso(self, *_):
        self.assertEqual(ptm.main(["CODE"]), 0)

    @patch.object(ptm, "APP_ID", "app")
    @patch.object(ptm, "APP_SECRET", "sec")
    @patch.object(ptm, "trocar_code_por_token", return_value={"access_token": "curto"})
    @patch.object(ptm, "trocar_por_longa_duracao", return_value={"access_token": "longo"})
    @patch.object(ptm, "listar_contas_anuncio", return_value=[])
    def test_sucesso_sem_contas(self, *_):
        self.assertEqual(ptm.main(["CODE"]), 0)


if __name__ == "__main__":
    unittest.main()
