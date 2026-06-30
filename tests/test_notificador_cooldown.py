"""
tests/test_notificador_cooldown.py — cooldown de alertas Telegram por chave.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.notificador as notificador


class TestNotificadorCooldown(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_path = notificador._COOLDOWN_PATH
        notificador._COOLDOWN_PATH = Path(self.tmp.name) / "alertas_cooldown.json"

    def tearDown(self):
        notificador._COOLDOWN_PATH = self._orig_path
        self.tmp.cleanup()

    @patch.object(notificador, "_enviar", return_value=True)
    @patch.object(notificador, "time")
    def test_primeira_chamada_envia(self, mock_time, mock_enviar):
        mock_time.time.return_value = 1000.0
        self.assertTrue(
            notificador.alertar_gestor("msg teste", chave="teste:1", cooldown_segundos=7200)
        )
        mock_enviar.assert_called_once()

    @patch.object(notificador, "_enviar", return_value=True)
    @patch.object(notificador, "time")
    def test_segunda_dentro_do_cooldown_nao_envia(self, mock_time, mock_enviar):
        mock_time.time.side_effect = [1000.0, 1001.0]
        notificador.alertar_gestor("msg", chave="dup", cooldown_segundos=7200)
        mock_enviar.reset_mock()
        self.assertFalse(notificador.alertar_gestor("msg", chave="dup", cooldown_segundos=7200))
        mock_enviar.assert_not_called()

    @patch.object(notificador, "_enviar", return_value=True)
    @patch.object(notificador, "time")
    def test_apos_cooldown_envia_novamente(self, mock_time, mock_enviar):
        mock_time.time.side_effect = [1000.0, 9000.0]
        notificador.alertar_gestor("msg", chave="expira", cooldown_segundos=7200)
        mock_enviar.reset_mock()
        self.assertTrue(notificador.alertar_gestor("msg", chave="expira", cooldown_segundos=7200))
        mock_enviar.assert_called_once()

    @patch.object(notificador, "_enviar", return_value=True)
    @patch.object(notificador, "time")
    def test_chaves_diferentes_nao_se_bloqueiam(self, mock_time, mock_enviar):
        mock_time.time.return_value = 1000.0
        notificador.alertar_gestor("a", chave="chave_a", cooldown_segundos=7200)
        notificador.alertar_gestor("b", chave="chave_b", cooldown_segundos=7200)
        self.assertEqual(mock_enviar.call_count, 2)

    @patch.object(notificador, "alertar", return_value=True)
    @patch.object(notificador, "alertar_gestor", return_value=True)
    @patch.object(notificador, "time")
    def test_alertar_critico_respeita_cooldown(self, mock_time, mock_gestor, mock_alert):
        mock_time.time.side_effect = [1000.0, 1001.0]
        notificador.alertar_critico("urgente", chave="crit:1", cooldown_segundos=7200)
        mock_gestor.reset_mock()
        mock_alert.reset_mock()
        self.assertFalse(notificador.alertar_critico("urgente", chave="crit:1", cooldown_segundos=7200))
        mock_gestor.assert_not_called()
        mock_alert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
