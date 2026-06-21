"""
tests/test_whatsapp.py — core/whatsapp.py (sem rede).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.whatsapp as wpp


class TestWhatsApp(unittest.TestCase):
    @patch.multiple(wpp, WHATSAPP_API_TYPE="evolution", WHATSAPP_API_URL="", WHATSAPP_API_KEY="", WHATSAPP_INSTANCE="")
    def test_nao_configurado_retorna_false(self):
        with self.assertLogs("whatsapp", level="WARNING"):
            self.assertFalse(wpp.enviar_mensagem("5511999999999", "oi"))

    @patch.object(wpp, "request")
    @patch.multiple(
        wpp,
        WHATSAPP_API_TYPE="evolution",
        WHATSAPP_API_URL="http://evo",
        WHATSAPP_API_KEY="key",
        WHATSAPP_INSTANCE="inst",
    )
    def test_evolution_sucesso(self, mock_request):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        mock_request.return_value = r
        self.assertTrue(wpp.enviar_mensagem("5511999999999", "venda"))

    @patch.object(wpp, "request", side_effect=RuntimeError("timeout"))
    @patch.multiple(
        wpp,
        WHATSAPP_API_TYPE="evolution",
        WHATSAPP_API_URL="http://evo",
        WHATSAPP_API_KEY="key",
        WHATSAPP_INSTANCE="inst",
    )
    def test_evolution_falha(self, *_):
        with self.assertLogs("whatsapp", level="ERROR"):
            self.assertFalse(wpp.enviar_mensagem("5511999999999", "venda"))

    @patch.object(wpp, "enviar_mensagem", return_value=True)
    @patch.object(wpp, "WHATSAPP_NUMERO_DESTINO", "5511999999999")
    def test_notificar_venda(self, mock_enviar):
        self.assertTrue(wpp.notificar_venda("mercadolivre", "P1", "Kit", 49.9))
        mock_enviar.assert_called_once()

    @patch.object(wpp, "WHATSAPP_NUMERO_DESTINO", "")
    def test_notificar_venda_sem_destino(self):
        with self.assertLogs("whatsapp", level="WARNING"):
            self.assertFalse(wpp.notificar_venda("magalu", "P1", "Kit", 10.0))

    @patch.object(wpp, "request")
    @patch.multiple(
        wpp,
        WHATSAPP_API_TYPE="meta",
        WHATSAPP_BUSINESS_TOKEN="tok",
        WHATSAPP_PHONE_ID="pid",
    )
    def test_meta_envio_direto(self, mock_request):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        mock_request.return_value = r
        self.assertTrue(wpp._enviar_meta("5511999999999", "msg"))

    @patch.object(wpp, "_enviar_meta", return_value=True)
    @patch.multiple(
        wpp,
        WHATSAPP_API_TYPE="meta",
        WHATSAPP_BUSINESS_TOKEN="tok",
        WHATSAPP_PHONE_ID="pid",
    )
    def test_meta_api_type(self, mock_meta):
        self.assertTrue(wpp.enviar_mensagem("5511999999999", "msg"))
        mock_meta.assert_called_once()


if __name__ == "__main__":
    unittest.main()
