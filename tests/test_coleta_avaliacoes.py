"""tests/test_coleta_avaliacoes.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.ml import coleta_avaliacoes as ca
from tests.http_fixtures import make_http_response


class TestColetaAvaliacoes(unittest.TestCase):
    @patch.object(ca, "request")
    def test_resposta_vazia(self, mock_req):
        mock_req.return_value = make_http_response(json_body={"reviews": []})
        self.assertEqual(ca.buscar_avaliacoes_item("MLB1"), [])

    @patch.object(ca, "request")
    def test_reviews_com_texto(self, mock_req):
        mock_req.return_value = make_http_response(
            json_body={
                "reviews": [
                    {
                        "content": "Chegou vazando",
                        "rate": 2,
                        "title": "Ruim",
                        "date_created": "2026-01-01T00:00:00Z",
                    }
                ]
            }
        )
        out = ca.buscar_avaliacoes_item("MLB1")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["texto"], "Chegou vazando")
        self.assertEqual(out[0]["nota_estrelas"], 2)
        self.assertEqual(out[0]["titulo_curto"], "Ruim")

    @patch.object(ca, "incrementar")
    @patch.object(ca, "request")
    def test_reviews_403_lista_vazia(self, mock_req, mock_inc):
        mock_req.return_value = make_http_response(status_code=403, json_body={})
        self.assertEqual(ca.buscar_avaliacoes_item("MLB1"), [])
        mock_inc.assert_any_call("ml.reviews.http_403")

    @patch.object(ca, "request")
    def test_erro_de_rede(self, mock_req):
        mock_req.side_effect = RuntimeError("timeout")
        self.assertEqual(ca.buscar_avaliacoes_item("MLB1"), [])
        self.assertEqual(ca.buscar_perguntas_item("MLB1"), [])

    @patch.object(ca, "request")
    def test_perguntas(self, mock_req):
        mock_req.return_value = make_http_response(
            json_body={
                "questions": [
                    {"text": "Qual o prazo?", "status": "ANSWERED", "date_created": "2026-01-02"}
                ]
            }
        )
        out = ca.buscar_perguntas_item("MLB1")
        self.assertEqual(out[0]["texto"], "Qual o prazo?")

    def test_item_vazio(self):
        self.assertEqual(ca.buscar_avaliacoes_item(""), [])
        self.assertEqual(ca.buscar_perguntas_item(""), [])


if __name__ == "__main__":
    unittest.main()
