"""tests/test_github_secrets.py — gravar Secrets via gh CLI."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import github_secrets as gs


class TestGithubSecrets(unittest.TestCase):
    def setUp(self):
        gs._aviso_gh_token = False

    def test_sem_gh_cli_retorna_false_e_loga_error(self):
        with patch.object(gs.shutil, "which", return_value=None):
            with self.assertLogs("github_secrets", level="ERROR") as logs:
                self.assertFalse(gs.sync_secrets_github("at", "rt", prefix="ML"))
        self.assertTrue(any("gh CLI não encontrado" in line for line in logs.output))

    def test_actions_sem_gh_token_nao_chama_gh(self):
        env = {"GITHUB_ACTIONS": "true", "GH_TOKEN": "", "GH_REPO": "org/repo"}
        with patch.object(gs.shutil, "which", return_value="/usr/bin/gh"):
            with patch.object(gs.subprocess, "run") as run:
                with patch.dict(os.environ, env, clear=False):
                    with self.assertLogs("github_secrets", level="WARNING") as logs:
                        self.assertFalse(gs.sync_secrets_github("at", "rt", prefix="ML"))
        run.assert_not_called()
        self.assertTrue(any("GH_TOKEN vazio" in line for line in logs.output))

    def test_actions_sem_gh_token_avisa_uma_vez_por_processo(self):
        env = {"GITHUB_ACTIONS": "true", "GH_TOKEN": "", "GH_REPO": "org/repo"}
        with patch.object(gs.shutil, "which", return_value="/usr/bin/gh"):
            with patch.object(gs.subprocess, "run") as run:
                with patch.dict(os.environ, env, clear=False):
                    with self.assertLogs("github_secrets", level="WARNING") as logs:
                        self.assertFalse(gs.sync_secrets_github("at", "rt", prefix="ML"))
                        self.assertFalse(gs.sync_secrets_github("at", "rt", prefix="BLING"))
        run.assert_not_called()
        avisos = [line for line in logs.output if "GH_TOKEN vazio" in line]
        self.assertEqual(len(avisos), 1)

    def test_actions_com_pat_grava_access_e_refresh(self):
        env = {"GITHUB_ACTIONS": "true", "GH_TOKEN": "ghp_x", "GH_REPO": "org/repo"}
        with patch.object(gs.shutil, "which", return_value="/usr/bin/gh"):
            with patch.object(gs.subprocess, "run", return_value=MagicMock()) as run:
                with patch.dict(os.environ, env, clear=False):
                    self.assertTrue(gs.sync_secrets_github("at", "rt", prefix="ML"))
        self.assertEqual(run.call_count, 2)
        nomes = [c.args[0][3] for c in run.call_args_list]
        self.assertEqual(nomes, ["ML_ACCESS_TOKEN", "ML_REFRESH_TOKEN"])

    def test_gh_secret_set_falha_loga_stderr(self):
        env = {"GITHUB_ACTIONS": "true", "GH_TOKEN": "ghp_x", "GH_REPO": "org/repo"}
        err = subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 403: Resource not accessible by integration")
        with patch.object(gs.shutil, "which", return_value="/usr/bin/gh"):
            with patch.object(gs.subprocess, "run", side_effect=err):
                with patch.dict(os.environ, env, clear=False):
                    with self.assertLogs("github_secrets", level="ERROR") as logs:
                        self.assertFalse(gs.sync_secrets_github("at", None, prefix="ML"))
        self.assertTrue(any("HTTP 403" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
