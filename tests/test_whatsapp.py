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
    @patch.multiple(wpp, WHATSAPP_API_TYPE="meta", WHATSAPP_BUSINESS_TOKEN="", WHATSAPP_PHONE_ID="")
    def test_nao_configurado_retorna_false(self):
        with self.assertLogs("whatsapp", level="WARNING"):
            self.assertFalse(wpp.enviar_mensagem("5511999999999", "oi"))

    @patch.multiple(wpp, WHATSAPP_API_TYPE="evolution")
    def test_evolution_desligado(self):
        with self.assertLogs("whatsapp", level="WARNING"):
            self.assertFalse(wpp.enviar_mensagem("5511999999999", "venda"))

    @patch("core.notificador.notificar_venda_gestor", return_value=True)
    def test_notificar_venda(self, mock_tg):
        self.assertTrue(wpp.notificar_venda("mercadolivre", "P1", "Kit", 49.9))
        mock_tg.assert_called_once()

    def test_grupo_desligado(self):
        with self.assertLogs("whatsapp", level="INFO"):
            self.assertFalse(wpp.enviar_mensagem_grupo("120363@g.us", "oi"))
        self.assertFalse(wpp.whatsapp_grupo_manicures_configurado())
        self.assertEqual(wpp.buscar_mensagens_grupo_recentes(), [])

    def test_enviar_grupo_manicures_manual(self):
        with self.assertLogs("whatsapp", level="INFO"):
            self.assertFalse(wpp.enviar_grupo_manicures("promo"))

    @patch("core.notificador.TELEGRAM_GESTOR_CHAT_ID", "")
    @patch("core.notificador.TELEGRAM_CHAT_ID", "")
    @patch("core.notificador.TELEGRAM_TOKEN", "")
    def test_notificar_venda_sem_destino(self, *_):
        with self.assertLogs("notificador", level="WARNING"):
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
