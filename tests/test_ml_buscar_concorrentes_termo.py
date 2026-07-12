"""
tests/test_ml_buscar_concorrentes_termo.py
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
class TestBuscarConcorrentesPorTermo(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _http(self, mock_http):
        self.mock_http = mock_http

    def test_termo_vazio(self):
        self.assertEqual(ml_client.buscar_concorrentes_por_termo(""), [])

    def test_exclui_proprio_vendedor(self):
        with patch.object(ml_client, "ML_SELLER_ID", "999"), patch.object(
            ml_client, "_enabled", return_value=True
        ), patch.object(ml_client, "_request_ml") as mock_req, patch.object(
            busca_termo_ml,
            "ML_BUSCA_TERMO_FALLBACK_PRODUCTS",
            False,
        ), patch.object(
            busca_termo_ml,
            "ML_BUSCA_TERMO_FALLBACK_CATALOGO",
            False,
        ), patch.object(
            busca_termo_ml,
            "ML_BUSCA_TERMO_FALLBACK_BRAVE",
            False,
        ), patch.object(
            busca_termo_ml,
            "ML_BUSCA_TERMO_FALLBACK_DDG",
            False,
        ):
            mock_req.return_value = _mock_resp({
                "results": [
                    {
                        "id": "MLB1",
                        "title": "Kit Impala Meu",
                        "price": 40,
                        "seller": {"id": "999"},
                        "shipping": {},
                        "condition": "new",
                        "sold_quantity": 1,
                    },
                    {
                        "id": "MLB2",
                        "title": "Kit Impala Concorrente",
                        "price": 35,
                        "seller": {"id": "888"},
                        "shipping": {"free_shipping": True},
                        "condition": "new",
                        "sold_quantity": 5,
                    },
                ]
            })
            out = ml_client.buscar_concorrentes_por_termo("kit impala", limite=5)
        mock_req.assert_called_once()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["item_id"], "MLB2")
        self.assertEqual(out[0]["preco"], 35.0)

    def test_403_com_token_usa_fallback(self):
        item_body = {
            "id": "MLB123",
            "title": "Kit Impala",
            "price": 29.9,
            "seller": {"id": "888"},
            "shipping": {},
            "condition": "new",
            "sold_quantity": 8,
        }
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml"
        ) as mock_req, patch.object(ml_client, "listar_meus_anuncios", return_value=[]), patch.object(
            ml_client, "buscar_detalhes_concorrentes", return_value=[]
        ), patch("integracoes.ml.busca_termo_ml.ddg_buscar") as mock_ddg, patch.object(
            busca_termo_ml,
            "ML_BUSCA_TERMO_FALLBACK_CATALOGO",
            False,
        ), patch.object(
            busca_termo_ml,
            "ML_BUSCA_TERMO_FALLBACK_PRODUCTS",
            False,
        ), patch.object(
            busca_termo_ml,
            "ML_BUSCA_TERMO_FALLBACK_BRAVE",
            False,
        ):
            mock_req.side_effect = [
                _mock_resp({}, status=403),
                _mock_resp(item_body),
            ]
            mock_ddg.return_value = [
                {"url": "https://produto.mercadolivre.com.br/MLB-123-kit", "title": "Kit"}
            ]
            out = ml_client.buscar_concorrentes_por_termo("esmalte impala kit manicure", limite=25)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fonte_busca"], "ddg")

    def test_excecao_retorna_vazio(self):
        self.mock_http.side_effect = RuntimeError("rede")
        self.assertEqual(ml_client.buscar_concorrentes_por_termo("x"), [])


class TestSugestaoPreco(unittest.TestCase):
    @patch.object(ml_client, "_enabled", return_value=False)
    def test_listar_sugestoes_nao_configurado(self, *_):
        self.assertEqual(ml_client.listar_itens_com_sugestao_preco(), [])

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_listar_sugestoes_ok(self, _en, mock_req):
        mock_req.return_value = _mock_resp({"items": ["MLB1", "MLB2"]})
        self.assertEqual(ml_client.listar_itens_com_sugestao_preco(), ["MLB1", "MLB2"])

    @patch.object(ml_client, "_enabled", return_value=False)
    def test_buscar_sugestao_nao_configurado(self, *_):
        self.assertEqual(ml_client.buscar_sugestao_preco("MLB1"), {})

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_buscar_sugestao_ok(self, _en, mock_req):
        mock_req.return_value = _mock_resp({
            "item_id": "MLB1",
            "status": "active",
            "current_price": {"amount": 50},
            "suggested_price": {"amount": 45},
            "ratio": 0.9,
            "percent_difference": -10.0,
            "applicable_suggestion": True,
        })
        out = ml_client.buscar_sugestao_preco("MLB1")
        self.assertTrue(out.get("aplicavel"))
        self.assertEqual(out["preco_sugerido"], 45.0)


if __name__ == "__main__":
    unittest.main()
