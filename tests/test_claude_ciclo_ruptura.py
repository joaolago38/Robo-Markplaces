"""tests/test_claude_ciclo_ruptura.py"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integracoes.esmaltes import claude_ciclo_ruptura as ciclo


class TestClaudeCicloRuptura(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "claude_ciclo_ruptura.json"
        self.patcher = patch.object(ciclo, "CICLO_PATH", self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_antes_de_expor_e_maxima(self):
        self.assertEqual(ciclo.fase_claude_ruptura(), "maxima")

    def test_depois_de_expor_volta_moderada(self):
        ciclo.registrar_pulso_maxima()
        self.assertEqual(ciclo.fase_claude_ruptura(), "maxima")
        out = ciclo.marcar_exposto_datadog()
        self.assertTrue(out["exposto_datadog"])
        self.assertEqual(out["fase"], "moderada")
        self.assertEqual(ciclo.fase_claude_ruptura(), "moderada")
        # segundo pulso não reabre máxima
        ciclo.marcar_exposto_datadog()
        self.assertEqual(ciclo.fase_claude_ruptura(), "moderada")


if __name__ == "__main__":
    os.environ.setdefault("PYTEST_CURRENT_TEST", "1")
    unittest.main()
