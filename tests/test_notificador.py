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

    @patch.object(notificador, "formatar_data_hora_br", return_value="09/07 16:07")
    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_CHAT_ID", "123")
    @patch.object(notificador, "TELEGRAM_TOKEN", "token")
    def test_cabecalho_usa_horario_brasil(self, mock_request, mock_hora, *_patches):
        mock_request.return_value = _mock_resp()
        notificador.alertar("teste")
        texto = mock_request.call_args[1]["json"]["text"]
        self.assertIn("09/07 16:07", texto)
        mock_hora.assert_called_once()

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

    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_CHAT_ID", "123")
    @patch.object(notificador, "TELEGRAM_TOKEN", "token")
    def test_fallback_sem_markdown_em_400(self, mock_request, *_patches):
        r_bad = MagicMock()
        r_bad.status_code = 400
        r_bad.text = '{"ok":false,"description":"Bad Request: can\'t parse entities"}'
        r_bad.raise_for_status = MagicMock(side_effect=Exception("should not"))
        r_ok = _mock_resp()
        mock_request.side_effect = [r_bad, r_ok]
        self.assertTrue(notificador.alertar("url com_underscore e *asterisco*"))
        self.assertEqual(mock_request.call_count, 2)
        primeiro = mock_request.call_args_list[0][1]["json"]
        segundo = mock_request.call_args_list[1][1]["json"]
        self.assertEqual(primeiro.get("parse_mode"), "Markdown")
        self.assertNotIn("parse_mode", segundo)


class TestNotificadorFoto(unittest.TestCase):
    def setUp(self):
        tg.reset()
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_cooldown = notificador._COOLDOWN_PATH
        notificador._COOLDOWN_PATH = Path(self._tmp.name) / "cooldown.json"
        self.foto = Path(self._tmp.name) / "g.png"
        self.foto.write_bytes(b"\x89PNG\r\n\x1a\n fake png bytes")

    def tearDown(self):
        notificador._COOLDOWN_PATH = self._orig_cooldown
        self._tmp.cleanup()

    @patch.object(notificador, "TELEGRAM_TOKEN", "")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "")
    def test_foto_sem_config_retorna_false(self):
        self.assertFalse(notificador._enviar_foto("", str(self.foto), "cap"))

    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_enviar_foto_gestor_usa_sendphoto(self, mock_request):
        mock_request.return_value = _mock_resp()
        ok = notificador.enviar_foto_gestor(str(self.foto), "legenda", _ignorar_cooldown=True)
        self.assertTrue(ok)
        url = mock_request.call_args[0][1]
        self.assertIn("sendPhoto", url)
        self.assertIn("files", mock_request.call_args[1])
        self.assertEqual(mock_request.call_args[1]["data"]["chat_id"], "g1")

    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_foto_arquivo_inexistente_retorna_false(self, mock_request):
        ok = notificador._enviar_foto("g1", str(self.foto) + ".naoexiste", "x")
        self.assertFalse(ok)
        mock_request.assert_not_called()

    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_foto_respeita_cooldown(self, mock_request):
        mock_request.return_value = _mock_resp()
        primeira = notificador.enviar_foto_gestor(str(self.foto), "x", chave="k-foto", cooldown_segundos=999)
        segunda = notificador.enviar_foto_gestor(str(self.foto), "x", chave="k-foto", cooldown_segundos=999)
        self.assertTrue(primeira)
        self.assertFalse(segunda)


class TestNotificadorPerguntarGestor(unittest.TestCase):
    @patch.object(notificador, "TELEGRAM_TOKEN", "")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "")
    def test_perguntar_gestor_sem_config_retorna_false(self, *_patches):
        # Fail-closed: sem Telegram não efetiva Ads
        self.assertFalse(notificador.perguntar_gestor_e_aguardar("ok?", timeout_segundos=1))

    @patch.object(notificador, "verificar_token", return_value=True)
    @patch.object(notificador, "pode_enviar", return_value=True)
    @patch.object(notificador, "time")
    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_perguntar_gestor_sem_contexto_mensagem_inalterada(
        self, mock_request, mock_time, *_patches
    ):
        mock_time.monotonic.side_effect = [0, 100]
        mock_time.sleep = MagicMock()
        mock_request.return_value = _mock_resp()
        notificador.perguntar_gestor_e_aguardar("ligar ads?", timeout_segundos=5)
        texto = mock_request.call_args[1]["json"]["text"]
        self.assertIn("ligar ads?", texto)
        self.assertIn("_Responda abaixo:_", texto)
        self.assertNotIn("*Contexto:*", texto)

    @patch.object(notificador, "verificar_token", return_value=True)
    @patch.object(notificador, "pode_enviar", return_value=True)
    @patch.object(notificador, "_gerar_justificativa_decisao", return_value="ACOS subiu nas últimas 2 semanas.")
    @patch.object(notificador, "time")
    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_perguntar_gestor_com_contexto_inclui_justificativa(
        self, mock_request, mock_time, mock_just, *_patches
    ):
        mock_time.monotonic.side_effect = [0, 100]
        mock_time.sleep = MagicMock()
        mock_request.return_value = _mock_resp()
        ctx = {"decisao": "pausar", "acos_atual": 0.35}
        notificador.perguntar_gestor_e_aguardar("pausar?", timeout_segundos=5, contexto_decisao=ctx)
        mock_just.assert_called_once_with(ctx)
        texto = mock_request.call_args[1]["json"]["text"]
        self.assertIn("ACOS subiu", texto)

    @patch.object(notificador, "verificar_token", return_value=True)
    @patch.object(notificador, "pode_enviar", return_value=True)
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

    @patch.object(notificador, "verificar_token", return_value=True)
    @patch.object(notificador, "pode_enviar", return_value=True)
    @patch.object(notificador, "time")
    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_perguntar_gestor_sim_via_callback(self, mock_request, mock_time, *_):
        mock_time.monotonic.side_effect = [0, 1, 2, 100]
        mock_time.sleep = MagicMock()
        send_resp = _mock_resp()
        poll_resp = MagicMock()
        poll_resp.raise_for_status = MagicMock()
        poll_resp.status_code = 200
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

    @patch.object(notificador, "verificar_token", return_value=True)
    @patch.object(notificador, "pode_enviar", return_value=True)
    @patch.object(notificador, "time")
    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_perguntar_gestor_timeout(self, mock_request, mock_time, *_):
        mock_time.monotonic.side_effect = [0, 100]
        mock_time.sleep = MagicMock()
        mock_request.return_value = _mock_resp()
        self.assertFalse(notificador.perguntar_gestor_e_aguardar("?", timeout_segundos=5))

    @patch.object(notificador, "verificar_token", return_value=False)
    @patch.object(notificador, "pode_enviar", return_value=False)
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "123:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    def test_perguntar_gestor_token_invalido_negado(self, *_):
        self.assertFalse(notificador.perguntar_gestor_e_aguardar("ok?", timeout_segundos=1))


class TestGestorTelegramConfigurado(unittest.TestCase):
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    def test_configurado(self):
        self.assertTrue(notificador.gestor_telegram_configurado())

    @patch.object(notificador, "TELEGRAM_TOKEN", "")
    @patch.object(notificador, "TELEGRAM_GESTOR_CHAT_ID", "g1")
    def test_sem_token(self):
        self.assertFalse(notificador.gestor_telegram_configurado())


class TestManiucresTelegram(unittest.TestCase):
    def setUp(self):
        tg.reset()
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_cooldown = notificador._COOLDOWN_PATH
        notificador._COOLDOWN_PATH = Path(self._tmp.name) / "alertas_cooldown.json"

    def tearDown(self):
        notificador._COOLDOWN_PATH = self._orig_cooldown
        self._tmp.cleanup()

    @patch.object(notificador, "TELEGRAM_MANICURES_CHAT_ID", "")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_manicures_nao_configurado(self):
        self.assertFalse(notificador.manicures_telegram_configurado())

    @patch.object(notificador, "request")
    @patch.object(notificador, "TELEGRAM_MANICURES_CHAT_ID", "manicures-1")
    @patch.object(notificador, "TELEGRAM_TOKEN", "tok")
    def test_enviar_telegram_manicures(self, mock_request):
        mock_request.return_value = _mock_resp()
        self.assertTrue(notificador.enviar_telegram_manicures("Kit promo"))
        payload = mock_request.call_args[1]["json"]
        self.assertEqual(payload["chat_id"], "manicures-1")
        self.assertIn("Promo manicures", payload["text"])


if __name__ == "__main__":
    unittest.main()
