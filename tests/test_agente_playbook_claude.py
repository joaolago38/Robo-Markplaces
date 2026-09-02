"""tests/test_agente_playbook_claude.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from agentes.ml import agente_playbook_claude as ag


class TestAgentePlaybookClaude(unittest.TestCase):
    def test_payload_dez_candidatos_sem_mlb(self):
        payload = ag.payload_entrada(limite=10)
        self.assertEqual(len(payload["produtos_candidatos"]), 10)
        self.assertTrue(payload["produtos_candidatos"][0].get("sku"))
        self.assertTrue(all(not p.get("publicado") for p in payload["produtos_candidatos"]))
        self.assertIn("MLB publicado", payload["aviso"])

    def test_fallback_tem_tabela_e_top3(self):
        txt = ag.fallback_demanda_alta(ag.payload_entrada(limite=10))
        self.assertIn("Produto | Sinal de demanda", txt)
        self.assertIn("IMP-MIMO-003", txt)
        self.assertIn("Top 3", txt)
        self.assertIn("0%", txt)

    @patch.object(ag, "sintetizar_claude", return_value="tabela fake")
    def test_executar_grava_playbook(self, _sint):
        with patch.object(ag, "escrever_json_atomico"):
            out = ag.executar(playbook_id="demanda_alta", limite=10)
        self.assertTrue(out["ok"])
        self.assertEqual(out["playbook_id"], "demanda_alta")
        self.assertEqual(out["texto"], "tabela fake")
        self.assertFalse(out["usou_fallback"])


if __name__ == "__main__":
    unittest.main()
