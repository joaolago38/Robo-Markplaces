"""
tests/test_busca_termo_ml.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.http_fixtures import make_http_response

from integracoes.ml import busca_termo_ml, ml_client


def _mock_resp(body: dict, status: int = 200) -> MagicMock:
    return make_http_response(status_code=status, json_body=body)


@pytest.mark.usefixtures("env_tokens")
class TestExtrairItemIdMl(unittest.TestCase):
    def test_url_produto(self):
        self.assertEqual(
            busca_termo_ml.extrair_item_id_ml(
                "https://produto.mercadolivre.com.br/MLB-123456789-kit-impala"
            ),
            "MLB123456789",
        )

    def test_id_direto(self):
        self.assertEqual(busca_termo_ml.extrair_item_id_ml("MLB9876543210"), "MLB9876543210")

    def test_vazio(self):
        self.assertIsNone(busca_termo_ml.extrair_item_id_ml(""))


@pytest.mark.usefixtures("env_tokens")
class TestExecutarBuscaTermo(unittest.TestCase):
    def test_api_ok_retorna_direto(self):
        item = {
            "id": "MLB2",
            "title": "Kit Impala",
            "price": 35,
            "seller": {"id": "888"},
            "shipping": {"free_shipping": True},
            "condition": "new",
            "sold_quantity": 5,
        }
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml"
        ) as mock_req:
            mock_req.return_value = _mock_resp({"results": [item]})
            out = busca_termo_ml.executar_busca_termo("kit impala", limite=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fonte_busca"], "api")

    def test_403_usa_fallback_ddg(self):
        item_body = {
            "id": "MLB123",
            "title": "Kit Impala 5 esmaltes",
            "price": 29.9,
            "seller": {"id": "888"},
            "shipping": {},
            "condition": "new",
            "sold_quantity": 12,
        }
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml"
        ) as mock_req, patch.object(
            ml_client, "listar_meus_anuncios", return_value=[]
        ), patch.object(
            ml_client, "buscar_detalhes_concorrentes", return_value=[]
        ), patch(
            "integracoes.ml.busca_termo_ml.ddg_buscar"
        ) as mock_ddg, patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_CATALOGO", False
        ):
            mock_req.side_effect = [
                _mock_resp({}, status=403),
                _mock_resp(item_body),
            ]
            mock_ddg.return_value = [
                {
                    "url": "https://produto.mercadolivre.com.br/MLB-123-kit",
                    "title": "Kit Impala",
                }
            ]
            out = busca_termo_ml.executar_busca_termo("esmalte impala kit", limite=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["item_id"], "MLB123")
        self.assertEqual(out[0]["fonte_busca"], "ddg")

    def test_fallback_catalogo(self):
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml"
        ) as mock_req, patch.object(
            ml_client, "listar_meus_anuncios", return_value=[]
        ), patch.object(
            ml_client,
            "buscar_detalhes_concorrentes",
            return_value=[
                {
                    "id": "MLB9",
                    "titulo": "Kit Anita",
                    "preco": 40.0,
                    "frete_gratis": True,
                    "condicao": "new",
                    "quantidade_vendida": 3,
                }
            ],
        ), patch.object(busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_DDG", False):
            mock_req.return_value = _mock_resp({}, status=403)
            out = busca_termo_ml.executar_busca_termo(
                "kit anita",
                limite=5,
                item_id_referencia="MLB_REF",
            )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fonte_busca"], "catalogo")


if __name__ == "__main__":
    unittest.main()
