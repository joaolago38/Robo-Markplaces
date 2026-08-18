"""Garante que o cache saude-heartbeats cobre todas as fontes do Vigia."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = Path(__file__).resolve().parent.parent
ACTION = ROOT / ".github" / "actions" / "saude-heartbeats" / "action.yml"
PATHS_TXT = ROOT / "catalogo" / "saude_heartbeats_paths.txt"
FONTES = ROOT / "catalogo" / "datadog_vigia_fontes.json"
VIGIA_HISTORY = "logs/datadog_vigia_history.json"


def _paths_catalogo() -> list[str]:
    linhas = []
    for linha in PATHS_TXT.read_text(encoding="utf-8").splitlines():
        s = linha.strip()
        if s and not s.startswith("#"):
            linhas.append(s)
    return linhas


class TestSaudeHeartbeatsCache(unittest.TestCase):
    def test_action_e_catalogo_tem_as_mesmas_paths(self):
        action = ACTION.read_text(encoding="utf-8")
        catalogo = _paths_catalogo()
        self.assertGreaterEqual(len(catalogo), 10)
        for path in catalogo:
            self.assertIn(path, action, path)
        self.assertNotIn(VIGIA_HISTORY, catalogo)
        self.assertNotIn(VIGIA_HISTORY, action)
        self.assertIn("actions/cache/restore@v4", action)
        self.assertIn("actions/cache/save@v4", action)
        self.assertNotIn("uses: actions/cache@v4", action)

    def test_fontes_vigia_exceto_historico_proprio_estao_no_cache(self):
        fontes = json.loads(FONTES.read_text(encoding="utf-8"))
        catalogo = set(_paths_catalogo())
        action = ACTION.read_text(encoding="utf-8")
        for fonte in fontes:
            path = fonte.get("path") or ""
            if not path or path == VIGIA_HISTORY:
                continue
            self.assertIn(path, catalogo, fonte.get("id"))
            self.assertIn(path, action, fonte.get("id"))


if __name__ == "__main__":
    unittest.main()
