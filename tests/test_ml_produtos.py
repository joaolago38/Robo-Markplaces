"""
tests/test_ml_produtos.py — rotação do refresh_token ML e listar_meus_anuncios.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.config as cfg
import core.token_manager as tm
from integracoes.ml import ml_client


def _mock_resp(body):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    return r


class TestMlRefreshRotacao(unittest.TestCase):
    def setUp(self):
        tm._token_cache_ml["access_token"] = None
        tm._token_cache_ml["expires_at"] = 0
        tm._ml_refresh_efetivo["valor"] = None
        self._orig_refresh = cfg.ML_REFRESH_TOKEN
        cfg.ML_REFRESH_TOKEN = "refresh_antigo"

    def tearDown(self):
        cfg.ML_REFRESH_TOKEN = self._orig_refresh
        tm._token_cache_ml["access_token"] = None
        tm._token_cache_ml["expires_at"] = 0
        tm._ml_refresh_efetivo["valor"] = None

    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        ML_CLIENT_ID="cid",
        ML_CLIENT_SECRET="sec",
    )
    def test_ml_refresh_captura_novo_token(self, mock_request):
        mock_request.return_value = _mock_resp(
            {
                "access_token": "acc_novo",
                "expires_in": 21600,
                "refresh_token": "refresh_novo",
            }
        )
        tok = tm._renovar_token_ml()
        self.assertEqual(tok, "acc_novo")
        self.assertEqual(tm._ml_refresh_efetivo["valor"], "refresh_novo")
        self.assertEqual(cfg.ML_REFRESH_TOKEN, "refresh_novo")

    @patch.object(tm, "request")
    @patch.multiple(
        cfg,
        ML_CLIENT_ID="cid",
        ML_CLIENT_SECRET="sec",
    )
    def test_segunda_renovacao_usa_refresh_rotacionado(self, mock_request):
        tm._ml_refresh_efetivo["valor"] = "refresh_rotacionado"

        mock_request.return_value = _mock_resp(
            {
                "access_token": "acc2",
                "expires_in": 21600,
                "refresh_token": "refresh_rotacionado2",
            }
        )
        tm._renovar_token_ml()

        call_data = mock_request.call_args[1]["data"]
        self.assertEqual(call_data["refresh_token"], "refresh_rotacionado")
        self.assertNotEqual(call_data["refresh_token"], "refresh_antigo")

    @patch.object(tm, "request")
    def test_tokens_ml_atuais_nao_renova(self, mock_request):
        tm._token_cache_ml["access_token"] = "acc_cache"
        tm._ml_refresh_efetivo["valor"] = "ref_cache"
        cfg.ML_ACCESS_TOKEN = "acc_env"
        cfg.ML_REFRESH_TOKEN = "ref_env"

        out = tm.tokens_ml_atuais()

        mock_request.assert_not_called()
        self.assertEqual(out["access_token"], "acc_cache")
        self.assertEqual(out["refresh_token"], "ref_cache")

    @patch.object(tm, "request")
    def test_tokens_shopee_atuais_nao_renova(self, mock_request):
        tm._token_cache_shopee["access_token"] = "sp_acc"
        tm._shopee_refresh_efetivo["valor"] = "sp_ref"

        out = tm.tokens_shopee_atuais()

        mock_request.assert_not_called()
        self.assertEqual(out["access_token"], "sp_acc")
        self.assertEqual(out["refresh_token"], "sp_ref")

    @patch.object(tm, "request")
    def test_tokens_magalu_atuais_nao_renova(self, mock_request):
        tm._token_cache_magalu["access_token"] = "mg_acc"
        tm._magalu_refresh_efetivo["valor"] = "mg_ref"

        out = tm.tokens_magalu_atuais()

        mock_request.assert_not_called()
        self.assertEqual(out["access_token"], "mg_acc")
        self.assertEqual(out["refresh_token"], "mg_ref")


class TestListarMeusAnuncios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._patch = patch.multiple(
            ml_client,
            ML_ACCESS_TOKEN="tok",
            ML_SELLER_ID="111",
        )
        cls._patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()

    @patch.object(ml_client, "get_token_ml", return_value="tok")
    @patch.object(ml_client, "request")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_listar_meus_anuncios_normaliza(self, _en, mock_request, _gt):
        search_resp = _mock_resp({"results": ["MLB1", "MLB2"]})
        items_resp = _mock_resp(
            [
                {
                    "code": 200,
                    "body": {
                        "id": "MLB1",
                        "title": "Produto A",
                        "price": 19.9,
                        "seller_sku": "SKU-A",
                        "status": "active",
                    },
                },
                {
                    "code": 200,
                    "body": {
                        "id": "MLB2",
                        "title": "Produto B",
                        "price": 29.0,
                        "seller_sku": "",
                        "status": "paused",
                    },
                },
            ]
        )
        mock_request.side_effect = [search_resp, items_resp]

        out = ml_client.listar_meus_anuncios()

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["item_id"], "MLB1")
        self.assertEqual(out[0]["preco"], 19.9)
        self.assertEqual(out[0]["status"], "active")
        self.assertEqual(out[0]["sku"], "SKU-A")
        self.assertEqual(out[1]["item_id"], "MLB2")
        self.assertEqual(out[1]["status"], "paused")

    @patch.object(ml_client, "_enabled", return_value=False)
    def test_listar_meus_anuncios_sem_credenciais(self, *_):
        self.assertEqual(ml_client.listar_meus_anuncios(), [])


if __name__ == "__main__":
    unittest.main()
