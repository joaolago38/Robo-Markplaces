"""
tests/test_notificador.py — NT01–NT07 (+ perguntar_gestor token vazio)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.notificador as notificador
from core import telegram_gate as tg


def _mock_resp():
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = {"result": {"message_id": 1}}
    return r


class TestNotificadorAlertar(unittest.TestCase):
    def setUp(self):
        tg.reset()
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_cooldown = notificador._COOLDOWN_PATH
        notificador._COOLDOWN_PATH = Path(self._tmp.name) / "alertas_cooldown.json"

    def tearDown(self):
        notificador._COOLDOWN_PATH = self._orig_cooldown
        self._tmp.cleanup()

    @patch("builtins.print")
    @patch.object(notificador, "TELEGRAM_CHAT_ID", "")
    @patch.object(notificador, "TELEGRAM_TOKEN", "")
    def test_NT01_alertar_sem_telegram_retorna_false(self, *_patches):
        with self.assertLogs("notificador", level="WARNING") as logs:
            self.assertFalse(notificador.alertar("msg"))
        self.assertTrue(any("NÃO entregue" in line for line in logs.output))

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

    @patch.object(notificador, "request", side_effect=Exception("https://api.telegram.org/botSECRET123/sendMessage"))
    @patch.object(notificador, "TELEGRAM_CHAT_ID", "123")
    @patch.object(notificador, "TELEGRAM_TOKEN", "token")
    def test_NT08_erro_nao_vaza_token_na_url(self, *_patches):
        with self.assertLogs("notificador", level="ERROR") as logs:
            notificador.alertar("msg")
        joined = "\n".join(logs.output)
        self.assertIn("bot***", joined)
        self.assertNotIn("SECRET123", joined)


class TestNotificadorPerguntarGestor(unittest.TestCase):
    @patch.object(notificador, "TELEGRAM_TOKEN", "")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "")
    def test_perguntar_gestor_sem_config_retorna_true(self, *_patches):
        self.assertTrue(notificador.perguntar_gestor_e_aguardar("ok?", timeout_segundos=1))

    @patch.object(notificador, "time")
    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_perguntar_gestor_sem_contexto_mensagem_inalterada(self, mock_request, mock_time):
        mock_time.monotonic.side_effect = [0, 100]
        mock_time.sleep = MagicMock()
        mock_request.return_value = _mock_resp()
        notificador.perguntar_gestor_e_aguardar("ligar ads?", timeout_segundos=5)
        texto = mock_request.call_args[1]["json"]["text"]
        self.assertIn("ligar ads?", texto)
        self.assertIn("_Responda abaixo:_", texto)
        self.assertNotIn("*Contexto:*", texto)

    @patch.object(notificador, "_gerar_justificativa_decisao", return_value="ACOS subiu nas últimas 2 semanas.")
    @patch.object(notificador, "time")
    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_perguntar_gestor_com_contexto_inclui_justificativa(
        self, mock_request, mock_time, mock_just
    ):
        mock_time.monotonic.side_effect = [0, 100]
        mock_time.sleep = MagicMock()
        mock_request.return_value = _mock_resp()
        ctx = {"decisao": "pausar", "acos_atual": 0.35}
        notificador.perguntar_gestor_e_aguardar("pausar?", timeout_segundos=5, contexto_decisao=ctx)
        mock_just.assert_called_once_with(ctx)
        texto = mock_request.call_args[1]["json"]["text"]
        self.assertIn("ACOS subiu", texto)

    @patch.object(notificador, "_gerar_justificativa_decisao", return_value=None)
    @patch.object(notificador, "time")
    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_perguntar_gestor_fallback_sem_justificativa(self, mock_request, mock_time, *_):
        mock_time.monotonic.side_effect = [0, 100]
        mock_time.sleep = MagicMock()
        mock_request.return_value = _mock_resp()
        notificador.perguntar_gestor_e_aguardar("?", timeout_segundos=5, contexto_decisao={"x": 1})
        texto = mock_request.call_args[1]["json"]["text"]
        self.assertNotIn("*Contexto:*", texto)
        self.assertIn("_Responda abaixo:_", texto)

    @patch.object(notificador, "time")
    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_perguntar_gestor_sim_via_callback(self, mock_request, mock_time):
        mock_time.monotonic.side_effect = [0, 1, 2, 100]
        mock_time.sleep = MagicMock()
        send_resp = _mock_resp()
        poll_resp = MagicMock()
        poll_resp.raise_for_status = MagicMock()
        poll_resp.json.return_value = {
            "result": [
                {
                    "update_id": 9,
                    "callback_query": {
                        "id": "cb1",
                        "data": "ads_sim",
                        "message": {"message_id": 1},
                    },
                }
            ]
        }
        mock_request.side_effect = [send_resp, poll_resp]
        self.assertTrue(notificador.perguntar_gestor_e_aguardar("ligar ads?", timeout_segundos=30))

    @patch.object(notificador, "time")
    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_perguntar_gestor_timeout(self, mock_request, mock_time):
        mock_time.monotonic.side_effect = [0, 100]
        mock_time.sleep = MagicMock()
        mock_request.return_value = _mock_resp()
        self.assertFalse(notificador.perguntar_gestor_e_aguardar("?", timeout_segundos=5))


class TestGestorTelegramConfigurado(unittest.TestCase):
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    def test_configurado(self):
        self.assertTrue(notificador.gestor_telegram_configurado())

    @patch.object(notificador, "TELEGRAM_TOKEN", "")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    def test_sem_token(self):
        self.assertFalse(notificador.gestor_telegram_configurado())


if __name__ == "__main__":
    unittest.main()
