"""
tests/test_notificador.py — NT01–NT07 (+ perguntar_gestor token vazio)
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.notificador as notificador


def _mock_resp():
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = {"result": {"message_id": 1}}
    return r


class TestNotificadorAlertar(unittest.TestCase):
    @patch("builtins.print")
    @patch.object(notificador, "TELEGRAM_CHAT_ID", "")
    @patch.object(notificador, "TELEGRAM_TOKEN", "")
    def test_NT01_alertar_sem_telegram_retorna_true(self, *_patches):
        self.assertTrue(notificador.alertar("msg"))

    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_CHAT_ID", "123")
    @patch.object(notificador, "TELEGRAM_TOKEN", "token")
    def test_NT02_alertar_chama_send_message(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp()
        mock_request.return_value.raise_for_status = MagicMock()
        notificador.alertar("teste")
        url = mock_request.call_args[0][1]
        self.assertIn("sendMessage", url)

    @patch.object(notificador, "request", side_effect=Exception("timeout"))
    @patch.object(notificador, "TELEGRAM_CHAT_ID", "123")
    @patch.object(notificador, "TELEGRAM_TOKEN", "token")
    def test_NT03_alertar_false_em_excecao(self, *_patches):
        self.assertFalse(notificador.alertar("msg"))

    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "gestor-99")
    @patch.object(notificador, "TELEGRAM_TOKEN", "token")
    def test_NT04_alertar_gestor_usa_chat_gestor(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp()
        mock_request.return_value.raise_for_status = MagicMock()
        notificador.alertar_gestor("msg")
        payload = mock_request.call_args[1]["json"]
        self.assertEqual(payload["chat_id"], "gestor-99")

    def test_NT05_alertar_critico_chama_ambos(self):
        with patch.object(notificador, "alertar", MagicMock(return_value=True)) as m_alert, patch.object(
            notificador, "alertar_gestor", MagicMock(return_value=True)
        ) as m_gestor:
            notificador.alertar_critico("URGENTE")
        m_gestor.assert_called_once()
        m_alert.assert_called_once()

    @patch("core.whatsapp.notificar_venda", return_value=True)
    def test_NT06_notificar_venda_whatsapp_delega_whatsapp(self, mock_nv):
        ok = notificador.notificar_venda_whatsapp("ml", "PED-1", "Kit", 59.90)
        self.assertTrue(ok)
        mock_nv.assert_called_once()

    @patch("core.whatsapp.notificar_venda", side_effect=Exception("boom"))
    def test_NT07_notificar_venda_whatsapp_false_em_excecao(self, _mock_nv):
        ok = notificador.notificar_venda_whatsapp("ml", "PED-1", "Kit", 59.90)
        self.assertFalse(ok)


class TestNotificadorPerguntarGestor(unittest.TestCase):
    @patch.object(notificador, "TELEGRAM_TOKEN", "")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "")
    def test_perguntar_gestor_sem_config_retorna_true(self, *_patches):
        self.assertTrue(notificador.perguntar_gestor_e_aguardar("ok?", timeout_segundos=1))


if __name__ == "__main__":
    unittest.main()
