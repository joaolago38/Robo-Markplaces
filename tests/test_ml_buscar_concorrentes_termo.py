"""
tests/test_ml_buscar_concorrentes_termo.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.ml import ml_client


def _mock_resp(body: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    if status >= 400:
        r.raise_for_status.side_effect = RuntimeError(f"HTTP {status}")
    return r


class TestBuscarConcorrentesPorTermo(unittest.TestCase):
    def test_termo_vazio(self):
        self.assertEqual(ml_client.buscar_concorrentes_por_termo(""), [])

    @patch.object(ml_client, "request")
    @patch.object(ml_client, "ML_SELLER_ID", "999")
    def test_exclui_proprio_vendedor(self, mock_request):
        mock_request.return_value = _mock_resp({
            "results": [
                {
                    "id": "MLB1",
                    "title": "Meu",
                    "price": 40,
                    "seller": {"id": "999"},
                    "shipping": {},
                    "condition": "new",
                    "sold_quantity": 1,
                },
                {
                    "id": "MLB2",
                    "title": "Concorrente",
                    "price": 35,
                    "seller": {"id": "888"},
                    "shipping": {"free_shipping": True},
                    "condition": "new",
                    "sold_quantity": 5,
                },
            ]
        })
        out = ml_client.buscar_concorrentes_por_termo("kit impala", limite=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["item_id"], "MLB2")
        self.assertEqual(out[0]["preco"], 35.0)

    @patch.object(ml_client, "request", side_effect=RuntimeError("rede"))
    def test_excecao_retorna_vazio(self, *_):
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
