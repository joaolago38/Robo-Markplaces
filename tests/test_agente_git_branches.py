"""
tests/test_agente_git_branches.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.orquestrador import agente_git_branches as agb


class AgenteGitBranchesTests(unittest.TestCase):
    @patch("agentes.orquestrador.agente_git_branches.executar_limpeza_branches")
    def test_executar_limpar_ok(self, mock_limpar):
        mock_limpar.return_value = {"ok": True, "remotas_deletadas": ["feature/x"]}
        out = agb.executar_limpar()
        self.assertTrue(out["ok"])
        mock_limpar.assert_called_once()

    @patch("agentes.orquestrador.agente_git_branches.criar_branch_de_main")
    def test_executar_criar_auto(self, mock_criar):
        mock_criar.return_value = {"ok": True, "branch": "cursor/20260705-1200", "criada": True}
        with patch("agentes.orquestrador.agente_git_branches._gerar_nome_branch_auto", return_value="cursor/20260705-1200"):
            out = agb.executar_criar("auto")
        self.assertTrue(out["ok"])
        mock_criar.assert_called_once()

    @patch("agentes.orquestrador.agente_git_branches.executar_limpar")
    @patch("agentes.orquestrador.agente_git_branches.executar_criar")
    def test_executar_criar_e_limpar(self, mock_criar, mock_limpar):
        mock_criar.return_value = {"ok": True, "branch": "cursor/foo", "criada": True}
        mock_limpar.return_value = {"ok": True, "remotas_deletadas": []}
        out = agb.executar(criar_branch="cursor/foo", limpar=True)
        self.assertTrue(out["ok"])
        mock_criar.assert_called_once()
        mock_limpar.assert_called_once()

    @patch("agentes.orquestrador.agente_git_branches.executar_criar")
    def test_executar_falha_criar(self, mock_criar):
        mock_criar.return_value = {"ok": False, "motivo": "alterações locais"}
        out = agb.executar(criar_branch="cursor/x", limpar=False)
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
