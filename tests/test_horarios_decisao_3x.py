"""tests/test_horarios_decisao_3x.py"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from core import telegram_explicacao as te
from core.config import ROOT


class TestHorariosDecisao3x(unittest.TestCase):
    def test_catalogo_existe_e_suficiente(self):
        path = ROOT / "catalogo" / "horarios_decisao_3x.json"
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(data["suficiente"])
        self.assertEqual(data["janelas_brt"]["manha"], "08:00")
        self.assertEqual(data["janelas_brt"]["tarde"], "14:00")
        self.assertEqual(data["janelas_brt"]["noite"], "21:00")
        self.assertIn("esmaltes_operacao", data["agentes_3x"])
        self.assertIn("orquestrador", data["agentes_manter_frequente"])

    def test_textos_telegram_3x(self):
        self.assertIn("3x/dia", te.HORARIOS_AGENTES["esmaltes_operacao"])
        self.assertIn("08:00", te.HORARIOS_AGENTES["esmaltes_operacao"])
        self.assertIn("21:00", te.HORARIOS_AGENTES["esmaltes_operacao"])
        self.assertIn("Claude 1×/noite", te.HORARIOS_AGENTES["monitor_masterprint_petg"])

    def test_workflows_tem_tres_crons(self):
        wf = Path(ROOT) / ".github" / "workflows"
        for nome in (
            "esmaltes_operacao.yml",
            "monitor_masterprint_petg.yml",
            "monitor_masterprint_escritorio.yml",
            "monitor_filamentos_ml.yml",
            "monitor_margem_vendas.yml",
        ):
            texto = (wf / nome).read_text(encoding="utf-8")
            self.assertGreaterEqual(texto.count("- cron:"), 3, msg=nome)
            self.assertIn("11 * * *", texto)
            self.assertIn("17 * * *", texto)
            self.assertIn("0 * * *", texto)


if __name__ == "__main__":
    unittest.main()
