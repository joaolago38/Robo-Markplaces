"""tests/test_brave_search.py — cota mensal e hard-stop Brave."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBraveCota(unittest.TestCase):
    def test_hard_stop_ao_esgotar(self):
        import core.brave_search as bs

        with tempfile.TemporaryDirectory() as tmp:
            uso = Path(tmp) / "brave_uso_mensal.json"
            with patch.object(bs, "_USO_PATH", uso), patch.object(
                bs,
                "_cfg",
                return_value=("chave", 2, 50.0, True),
            ), patch.object(bs, "request") as mock_req, patch.object(
                bs, "_alertar_cota"
            ), patch.object(bs, "_metricas"):
                mock_req.return_value = MagicMock(
                    status_code=200,
                    json=lambda: {"web": {"results": [{"url": "https://x.com", "title": "t"}]}},
                )
                self.assertEqual(len(bs.buscar_web("q1", contexto="t")), 1)
                self.assertEqual(len(bs.buscar_web("q2", contexto="t")), 1)
                # 3ª deve bloquear sem chamar HTTP
                mock_req.reset_mock()
                self.assertEqual(bs.buscar_web("q3", contexto="t"), [])
                mock_req.assert_not_called()
                st = bs.status_cota()
                self.assertEqual(st["consultas"], 2)
                self.assertTrue(st["esgotada"])

    def test_sem_chave_nao_consulta(self):
        import core.brave_search as bs

        with patch.object(bs, "_cfg", return_value=("", 1800, 80.0, True)), patch.object(
            bs, "request"
        ) as mock_req:
            self.assertEqual(bs.buscar_web("qualquer"), [])
            mock_req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
