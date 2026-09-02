"""
tests/test_client_http_errors.py — erros HTTP logados como ERROR, retorno vazio.
"""
import os
import sys
import unittest
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import integracoes.amazon.amazon_client as amz
import integracoes.magalu.magalu_client as mag
import integracoes.ml.ml_client as ml
import integracoes.shopee.shopee_client as shopee
from tests.http_fixtures import make_http_response


@pytest.mark.usefixtures("env_tokens")
class TestClientHttpErrors(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _http(self, mock_http):
        self.mock_http = mock_http

    def test_ml_listar_pedidos_403(self):
        with patch.object(ml, "ML_ACCESS_TOKEN", "t"), patch.object(ml, "ML_SELLER_ID", "1"):
            self.mock_http.return_value = make_http_response(status_code=403, text="scope")
            with self.assertLogs("ml_client", level="ERROR") as logs:
                self.assertEqual(ml.listar_pedidos(), [])
            self.assertTrue(any("ESCOPO" in line or "403" in line for line in logs.output))

    def test_magalu_listar_perguntas_401(self):
        with patch.object(mag, "MAGALU_ACCESS_TOKEN", "t"), patch.object(
            mag, "_canal_operando", return_value=True
        ):
            self.mock_http.return_value = make_http_response(status_code=401)
            with self.assertLogs("magalu_client", level="ERROR"):
                self.assertEqual(mag.listar_perguntas_nao_respondidas(), [])

    def test_amazon_listar_mensagens_rede(self):
        with patch.object(amz, "AMAZON_ACCESS_TOKEN", "t"), patch.object(
            amz, "_canal_operando", return_value=True
        ):
            self.mock_http.side_effect = RuntimeError("rede")
            with self.assertLogs("amazon_client", level="ERROR"):
                self.assertEqual(amz.listar_mensagens_nao_respondidas(), [])

    def test_shopee_listar_perguntas_403(self):
        with (
            patch.object(shopee, "SHOPEE_PARTNER_ID", "1"),
            patch.object(shopee, "SHOPEE_PARTNER_KEY", "k"),
            patch.object(shopee, "SHOPEE_SHOP_ID", "2"),
            patch.object(shopee, "SHOPEE_ACCESS_TOKEN", "t"),
            patch.object(shopee, "_canal_operando", return_value=True),
        ):
            self.mock_http.return_value = make_http_response(status_code=403)
            with self.assertLogs("shopee_client", level="ERROR"):
                out, ok = shopee._listar_perguntas_nao_respondidas_detalhado()
            self.assertEqual(out, [])
            self.assertFalse(ok)


class TestMascararSegredosHttp(unittest.TestCase):
    def test_redige_access_token_em_url(self):
        from core.http_errors import mascarar_segredos_http

        bruto = "GET https://partner.shopeemobile.com/api?access_token=segredo123&shop_id=1"
        out = mascarar_segredos_http(bruto)
        self.assertNotIn("segredo123", out)
        self.assertIn("access_token=***", out)

    def test_mascarar_telegram_path_sem_host(self):
        from core.http_errors import mascarar_segredos_http

        bruto = (
            "Max retries exceeded with url: /botSECRET123/sendPhoto "
            "(TimeoutError('The write operation timed out'))"
        )
        out = mascarar_segredos_http(bruto)
        self.assertNotIn("SECRET123", out)
        self.assertIn("/bot***/sendPhoto", out)

    def test_eh_timeout_rede_protocol_error(self):
        from core.http_errors import eh_timeout_rede

        exc = RuntimeError(
            "ProtocolError('Connection aborted.', TimeoutError('The write operation timed out'))"
        )
        self.assertTrue(eh_timeout_rede(exc))
        self.assertTrue(eh_timeout_rede(TimeoutError("timed out")))
        self.assertFalse(eh_timeout_rede(RuntimeError("HTTP 403")))


if __name__ == "__main__":
    unittest.main()
