"""tests/test_claude_toggle.py"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import claude_toggle as t


class TestClaudeToggle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "claude_toggle.json"
        self.patcher = patch.object(t, "TOGGLE_PATH", self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    @patch.object(t, "_cfg_env_ativo", return_value=True)
    def test_ligado_por_padrao(self, _):
        ok, motivo = t.claude_esta_ativo()
        self.assertTrue(ok)
        self.assertEqual(motivo, "")

    @patch.object(t, "_cfg_env_ativo", return_value=False)
    def test_env_desliga(self, _):
        ok, motivo = t.claude_esta_ativo()
        self.assertFalse(ok)
        self.assertIn("CLAUDE_ATIVO", motivo)

    @patch.object(t, "_cfg_env_ativo", return_value=True)
    def test_arquivo_desliga_e_liga(self, _):
        t.definir_ativo(False, motivo="pausa_teste", atualizado_por="test")
        ok, motivo = t.claude_esta_ativo()
        self.assertFalse(ok)
        self.assertIn("pausa_teste", motivo)

        t.definir_ativo(True, motivo="operacao", atualizado_por="test")
        ok2, _ = t.claude_esta_ativo()
        self.assertTrue(ok2)

    @patch.object(t, "_cfg_env_ativo", return_value=False)
    def test_arquivo_ligado_mas_env_prende(self, _):
        t.definir_ativo(True, motivo="operacao")
        ok, motivo = t.claude_esta_ativo()
        self.assertFalse(ok)
        self.assertIn("CLAUDE_ATIVO", motivo)

    @patch.object(t, "_cfg_env_ativo", return_value=True)
    def test_sem_credito_desliga_mesmo_com_actions_ligado(self, _):
        t.inativar_por_saldo()
        ok, motivo = t.claude_esta_ativo()
        self.assertFalse(ok)
        self.assertIn("sem_credito", motivo)
        self.assertTrue(t.sem_credito_ativo())

    @patch.object(t, "_cfg_env_ativo", return_value=False)
    def test_saldo_ok_religa_mesmo_com_actions_desligado(self, _):
        t.inativar_por_saldo()
        t.reativar_por_saldo()
        ok, motivo = t.claude_esta_ativo()
        self.assertTrue(ok)
        self.assertEqual(motivo, "")
        self.assertFalse(t.sem_credito_ativo())

    @patch.object(t, "_cfg_env_ativo", return_value=True)
    def test_pausa_manual_nao_e_religada_pelo_saldo(self, _):
        t.definir_ativo(False, motivo="pausa_manual", atualizado_por="manual")
        st = t.reativar_por_saldo()
        self.assertFalse(st["ativo"])
        ok, motivo = t.claude_esta_ativo()
        self.assertFalse(ok)
        self.assertIn("pausa_manual", motivo)

    @patch.object(t, "_cfg_env_ativo", return_value=True)
    def test_economia_creditos_e_religada_pelo_saldo(self, _):
        t.definir_ativo(False, motivo="economia_creditos", atualizado_por="cli")
        st = t.reativar_por_saldo()
        self.assertTrue(st["ativo"])
        ok, motivo = t.claude_esta_ativo()
        self.assertTrue(ok)
        self.assertEqual(motivo, "")


class TestPodeChamarToggle(unittest.TestCase):
    @patch("core.claude_toggle.claude_esta_ativo", return_value=(False, "pausa_manual"))
    def test_pode_chamar_respeita_toggle(self, _):
        from core import claude_orcamento as o

        ok, motivo = o.pode_chamar()
        self.assertFalse(ok)
        self.assertIn("desligado", motivo.lower())

    @patch("core.claude_toggle.claude_esta_ativo", return_value=(False, "CLAUDE_ATIVO=0"))
    def test_pode_chamar_forcar_ignora_toggle(self, _):
        from core import claude_orcamento as o

        with patch.object(o, "resumo", return_value={"bloqueado": False, "restante_usd": 4.0, "consumido_usd": 1.0, "orcamento_usd": 8.99}):
            with patch.object(o, "_cfg") as cfg:
                cfg.return_value.CLAUDE_ORCAMENTO_ATIVO = True
                ok, motivo = o.pode_chamar(origem="ruptura_impala", forcar=True)
        self.assertTrue(ok)
        self.assertEqual(motivo, "")


if __name__ == "__main__":
    unittest.main()
