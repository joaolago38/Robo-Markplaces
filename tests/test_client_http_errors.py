"""
tests/test_client_http_errors.py — erros HTTP logados como ERROR, retorno vazio.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import integracoes.ml.ml_client as ml
import integracoes.magalu.magalu_client as mag
import integracoes.amazon.amazon_client as amz
import integracoes.shopee.shopee_client as shopee


def _resp(status: int, text: str = "erro") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = {}
    r.raise_for_status = MagicMock()
    return r


class TestClientHttpErrors(unittest.TestCase):
    @patch.object(ml, "request")
    @patch.object(ml, "ML_ACCESS_TOKEN", "t")
    @patch.object(ml, "ML_SELLER_ID", "1")
    def test_ml_listar_pedidos_403(self, mock_request):
        mock_request.return_value = _resp(403, "scope")
        with self.assertLogs("ml_client", level="ERROR") as logs:
            self.assertEqual(ml.listar_pedidos(), [])
        self.assertTrue(any("ESCOPO" in line or "403" in line for line in logs.output))

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "t")
    def test_magalu_listar_perguntas_401(self, mock_request):
        mock_request.return_value = _resp(401)
        with self.assertLogs("magalu_client", level="ERROR"):
            self.assertEqual(mag.listar_perguntas_nao_respondidas(), [])

    @patch.object(amz, "request")
    @patch.object(amz, "AMAZON_ACCESS_TOKEN", "t")
    def test_amazon_listar_mensagens_rede(self, mock_request):
        mock_request.side_effect = RuntimeError("rede")
        with self.assertLogs("amazon_client", level="ERROR"):
            self.assertEqual(amz.listar_mensagens_nao_respondidas(), [])

    @patch.object(shopee, "request")
    @patch.object(shopee, "SHOPEE_PARTNER_ID", "1")
    @patch.object(shopee, "SHOPEE_PARTNER_KEY", "k")
    @patch.object(shopee, "SHOPEE_SHOP_ID", "2")
    @patch.object(shopee, "SHOPEE_ACCESS_TOKEN", "t")
    def test_shopee_listar_perguntas_403(self, mock_request):
        mock_request.return_value = _resp(403)
        with self.assertLogs("shopee_client", level="ERROR"):
            out, ok = shopee._listar_perguntas_nao_respondidas_detalhado()
        self.assertEqual(out, [])
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
