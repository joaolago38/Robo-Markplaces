"""
tests/test_log_cooldown.py — spam Datadog: 1º aviso sobe, o resto vira DEBUG.
"""
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import log_cooldown


class TestLogCooldown(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = Path(self._tmp.name) / "datadog_log_cooldown.json"
        log_cooldown.reset_para_teste(self._path)
        self._log = logging.getLogger("token_manager")

    def tearDown(self):
        log_cooldown.reset_para_teste()
        self._tmp.cleanup()

    def test_primeiro_sobe_warning_segundo_debug(self):
        with self.assertLogs("token_manager", level="DEBUG") as logs:
            ok1 = log_cooldown.log_com_cooldown(
                self._log,
                "teste:a",
                "aviso repetido",
                cooldown_segundos=3600,
            )
            ok2 = log_cooldown.log_com_cooldown(
                self._log,
                "teste:a",
                "aviso repetido",
                cooldown_segundos=3600,
            )
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertTrue(any("WARNING" in line and "aviso repetido" in line for line in logs.output))
        self.assertTrue(any("DEBUG" in line and "suprimido cooldown" in line for line in logs.output))
        self.assertTrue(self._path.is_file())

    def test_chaves_independentes(self):
        with self.assertLogs("token_manager", level="WARNING") as logs:
            log_cooldown.log_com_cooldown(self._log, "k1", "um", cooldown_segundos=3600)
            log_cooldown.log_com_cooldown(self._log, "k2", "dois", cooldown_segundos=3600)
        self.assertEqual(len(logs.output), 2)
