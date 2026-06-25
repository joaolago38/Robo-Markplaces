"""
tests/test_diagnostico_telegram.py
Cobre o diagnóstico de conexão Telegram (executar + impressão + main).
"""
import importlib.util
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "diagnostico_telegram", os.path.join(ROOT, "scripts", "diagnostico_telegram.py")
)
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)


def _mock_resp(status: int, body: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body or {}
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = RuntimeError(f"HTTP {status}")
    return r


class TestExecutar(unittest.TestCase):
    @patch.object(diag, "_verificar_credenciais", return_value={"ok": False, "erro": "Variável ausente: TELEGRAM_TOKEN"})
    def test_token_ausente_para_cedo(self, *_):
        out = diag.executar()
        self.assertFalse(out["ok"])
        self.assertIn("TELEGRAM_TOKEN", out["erro"])
        self.assertNotIn("getme", out["etapas"])

    @patch.object(diag, "_testar_alertar_gestor", return_value={"ok": True})
    @patch.object(diag, "_testar_alertar", return_value={"ok": True})
    @patch.object(
        diag,
        "_verificar_get_me",
        return_value={"ok": True, "username": "robomarkeplace_bot", "bot_id": 123},
    )
    @patch.object(
        diag,
        "_verificar_credenciais",
        return_value={"ok": True, "token_mascarado": "8935544842:AAHU...***", "chat_id": "1", "gestor_chat_id": "2"},
    )
    def test_fluxo_completo_ok(self, *_):
        out = diag.executar()
        self.assertTrue(out["ok"])
        self.assertEqual(out["etapas"]["getme"]["username"], "robomarkeplace_bot")

    @patch.object(diag, "_testar_alertar_gestor", return_value={"ok": True})
    @patch.object(diag, "_testar_alertar", return_value={"ok": False, "erro": "falha envio"})
    @patch.object(diag, "_verificar_get_me", return_value={"ok": True, "username": "bot", "bot_id": 1})
    @patch.object(
        diag,
        "_verificar_credenciais",
        return_value={"ok": True, "token_mascarado": "x...***", "chat_id": "1", "gestor_chat_id": "2"},
    )
    def test_alerta_falha_mantem_outras_etapas(self, *_):
        out = diag.executar()
        self.assertFalse(out["ok"])
        self.assertIn("alertar", out["etapas"])
        self.assertIn("alertar_gestor", out["etapas"])


class TestAlertar(unittest.TestCase):
    @patch("core.notificador.alertar", return_value=True)
    def test_alertar_ok(self, mock_alertar):
        out = diag._testar_alertar()
        self.assertTrue(out["ok"])
        mock_alertar.assert_called_once_with(diag.MSG_TESTE)

    @patch("core.notificador.alertar", return_value=False)
    def test_alertar_falha(self, *_):
        out = diag._testar_alertar()
        self.assertFalse(out["ok"])

    @patch("core.notificador.alertar_gestor", return_value=True)
    def test_alertar_gestor_ok(self, mock_gestor):
        out = diag._testar_alertar_gestor()
        self.assertTrue(out["ok"])
        mock_gestor.assert_called_once_with(diag.MSG_TESTE)

    @patch("core.notificador.alertar_gestor", return_value=False)
    def test_alertar_gestor_falha(self, *_):
        out = diag._testar_alertar_gestor()
        self.assertFalse(out["ok"])


class TestVerificarCredenciais(unittest.TestCase):
    @patch("core.config.TELEGRAM_GESTOR_CHAT_ID", "")
    @patch("core.config.TELEGRAM_CHAT_ID", "123")
    @patch("core.config.TELEGRAM_TOKEN", "tok")
    def test_credencial_gestor_ausente(self, *_):
        out = diag._verificar_credenciais()
        self.assertFalse(out["ok"])
        self.assertIn("TELEGRAM_GESTOR_CHAT_ID", out["erro"])


class TestVerificarGetMe(unittest.TestCase):
    @patch("core.http_client.request")
    @patch("core.config.TELEGRAM_TOKEN", "123:ABCsecret")
    def test_getme_sucesso(self, mock_request):
        mock_request.return_value = _mock_resp(
            200,
            {"ok": True, "result": {"id": 99, "username": "robomarkeplace_bot"}},
        )
        out = diag._verificar_get_me()
        self.assertTrue(out["ok"])
        self.assertEqual(out["username"], "robomarkeplace_bot")

    @patch("core.http_client.request")
    @patch("core.config.TELEGRAM_TOKEN", "123:ABCsecret")
    def test_getme_401(self, mock_request):
        mock_request.return_value = _mock_resp(401, {"ok": False, "description": "Unauthorized"})
        out = diag._verificar_get_me()
        self.assertFalse(out["ok"])
        self.assertIn("401", out["erro"])


class TestMascararToken(unittest.TestCase):
    def test_mascara_formato_bot(self):
        masc = diag._mascarar_token("8935544842:AAHUabcdefghijklmnop")
        self.assertIn("8935544842:AAHU", masc)
        self.assertIn("***", masc)
        self.assertNotIn("abcdefghijklmnop", masc)


class TestImprimir(unittest.TestCase):
    def test_imprime_credenciais_falha(self):
        diag._imprimir({"ok": False, "etapas": {"credenciais": {"ok": False, "erro": "x"}}})

    def test_imprime_resumo_ok(self):
        diag._imprimir({
            "ok": True,
            "etapas": {
                "credenciais": {"ok": True, "token_mascarado": "1:ABC...***", "chat_id": "1", "gestor_chat_id": "2"},
                "getme": {"ok": True, "username": "bot", "bot_id": 1},
                "alertar": {"ok": True},
                "alertar_gestor": {"ok": True},
            },
        })


class TestMain(unittest.TestCase):
    @patch.object(diag, "executar", return_value={"ok": True, "etapas": {}})
    def test_main_ok(self, *_):
        self.assertEqual(diag.main([]), 0)

    @patch.object(diag, "executar", return_value={"ok": False, "etapas": {"credenciais": {"ok": False}}})
    def test_main_falha(self, *_):
        self.assertEqual(diag.main([]), 1)


if __name__ == "__main__":
    unittest.main()
