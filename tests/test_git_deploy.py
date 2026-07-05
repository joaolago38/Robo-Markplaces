"""
tests/test_git_deploy.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import git_deploy as gd


class GitDeployTests(unittest.TestCase):
    def test_ignora_env_e_chaves(self):
        self.assertTrue(gd._deve_ignorar_arquivo(".env"))
        self.assertTrue(gd._deve_ignorar_arquivo("?? .env.local"))
        self.assertTrue(gd._deve_ignorar_arquivo(" M secrets.pem"))
        self.assertFalse(gd._deve_ignorar_arquivo("core/config.py"))

    def test_listar_arquivos_exclui_paths_e_sensiveis(self):
        status = {
            "alteracoes": [
                " M core/config.py",
                "?? arquivos-java-21/foo",
                "?? .env",
                "?? credentials.json",
            ]
        }
        arquivos = gd.listar_arquivos_para_stage(status, paths_excluir=("arquivos-java-21",))
        self.assertEqual(arquivos, ["core/config.py"])

    def test_listar_ignora_linha_curta(self):
        arquivos = gd.listar_arquivos_para_stage({"alteracoes": ["ab"]})
        self.assertEqual(arquivos, [])

    @patch("core.git_deploy._run_git")
    def test_obter_branch_atual(self, mock_git):
        mock_git.return_value = MagicMock(returncode=0, stdout="feature/x\n", stderr="")
        self.assertEqual(gd.obter_branch_atual(), "feature/x")
        mock_git.return_value = MagicMock(returncode=1, stdout="", stderr="erro")
        self.assertEqual(gd.obter_branch_atual(), "")

    @patch("core.git_deploy.obter_branch_atual", return_value="main")
    @patch("core.git_deploy._run_git")
    def test_obter_status(self, mock_git, _mock_br):
        mock_git.return_value = MagicMock(returncode=0, stdout=" M a.py\n", stderr="")
        out = gd.obter_status()
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_alteracoes"], 1)
        self.assertTrue(out["tem_alteracoes"])

    @patch("core.git_deploy._run_git")
    def test_adicionar_arquivos_vazio(self, mock_git):
        out = gd.adicionar_arquivos([])
        self.assertTrue(out["ok"])
        mock_git.assert_not_called()

    @patch("core.git_deploy._run_git")
    def test_adicionar_e_commit(self, mock_git):
        mock_git.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="[main abc] msg", stderr=""),
        ]
        self.assertTrue(gd.adicionar_arquivos(["a.py"])["ok"])
        commit = gd.criar_commit("feat: teste")
        self.assertTrue(commit["ok"])

    def test_commit_mensagem_vazia(self):
        out = gd.criar_commit("   ")
        self.assertFalse(out["ok"])

    @patch("core.git_deploy.obter_branch_atual", return_value="")
    def test_push_sem_branch(self, _mock_br):
        self.assertFalse(gd.push()["ok"])

    @patch("core.git_deploy._run_git")
    def test_push_sem_upstream(self, mock_git):
        mock_git.return_value = MagicMock(returncode=0, stdout="", stderr="")
        out = gd.push(remote="origin", branch="dev", set_upstream=False)
        self.assertTrue(out["ok"])
        args = mock_git.call_args[0]
        self.assertEqual(args[0], "push")
        self.assertNotIn("-u", args)

    @patch("core.git_deploy._run_git")
    def test_push_sem_force(self, mock_git):
        mock_git.return_value = MagicMock(returncode=0, stdout="", stderr="")
        out = gd.push(remote="origin", branch="main")
        self.assertTrue(out["ok"])
        self.assertIn("-u", mock_git.call_args[0])

    @patch("core.git_deploy.push")
    @patch("core.git_deploy.criar_commit")
    @patch("core.git_deploy.adicionar_arquivos")
    @patch("core.git_deploy.listar_arquivos_para_stage")
    @patch("core.git_deploy.obter_status")
    def test_executar_push_deploy_fluxo_ok(
        self, mock_status, mock_listar, mock_add, mock_commit, mock_push
    ):
        mock_status.return_value = {"ok": True, "branch": "main", "total_alteracoes": 1}
        mock_listar.return_value = ["core/x.py"]
        mock_add.return_value = {"ok": True}
        mock_commit.return_value = {"ok": True}
        mock_push.return_value = {"ok": True}
        out = gd.executar_push_deploy_git(mensagem_commit="deploy", remote="origin")
        self.assertTrue(out["ok"])
        self.assertTrue(out["commit_criado"])
        self.assertTrue(out["push_enviado"])

    @patch("core.git_deploy.obter_status")
    def test_executar_sem_alteracoes(self, mock_status):
        mock_status.return_value = {"ok": True, "branch": "main", "total_alteracoes": 0, "alteracoes": []}
        out = gd.executar_push_deploy_git(mensagem_commit="x")
        self.assertTrue(out["ok"])
        self.assertIn("nenhuma alteração", out["motivo"])

    @patch("core.git_deploy.listar_arquivos_para_stage", return_value=["a.py"])
    @patch("core.git_deploy.obter_status")
    def test_executar_dry_run(self, mock_status, _mock_listar):
        mock_status.return_value = {"ok": True, "branch": "main", "total_alteracoes": 1}
        out = gd.executar_push_deploy_git(mensagem_commit="x", dry_run=True)
        self.assertIn("dry_run", out["motivo"])

    @patch("core.git_deploy.adicionar_arquivos")
    @patch("core.git_deploy.listar_arquivos_para_stage", return_value=["a.py"])
    @patch("core.git_deploy.obter_status")
    def test_executar_falha_add(self, mock_status, _mock_listar, mock_add):
        mock_status.return_value = {"ok": True, "branch": "main"}
        mock_add.return_value = {"ok": False, "stderr": "add fail"}
        out = gd.executar_push_deploy_git(mensagem_commit="x")
        self.assertFalse(out["ok"])
        self.assertEqual(out["etapa"], "add")

    @patch("core.git_deploy.criar_commit")
    @patch("core.git_deploy.adicionar_arquivos")
    @patch("core.git_deploy.listar_arquivos_para_stage", return_value=["a.py"])
    @patch("core.git_deploy.obter_status")
    def test_executar_falha_commit(self, mock_status, _mock_listar, mock_add, mock_commit):
        mock_status.return_value = {"ok": True, "branch": "main"}
        mock_add.return_value = {"ok": True}
        mock_commit.return_value = {"ok": False, "stderr": "commit fail"}
        out = gd.executar_push_deploy_git(mensagem_commit="x")
        self.assertFalse(out["ok"])
        self.assertEqual(out["etapa"], "commit")

    @patch("core.git_deploy.push")
    @patch("core.git_deploy.criar_commit")
    @patch("core.git_deploy.adicionar_arquivos")
    @patch("core.git_deploy.listar_arquivos_para_stage", return_value=["a.py"])
    @patch("core.git_deploy.obter_status")
    def test_executar_falha_push(self, mock_status, _mock_listar, mock_add, mock_commit, mock_push):
        mock_status.return_value = {"ok": True, "branch": "main"}
        mock_add.return_value = {"ok": True}
        mock_commit.return_value = {"ok": True}
        mock_push.return_value = {"ok": False, "stderr": "push fail"}
        out = gd.executar_push_deploy_git(mensagem_commit="x")
        self.assertFalse(out["ok"])
        self.assertEqual(out["etapa"], "push")

    @patch("core.git_deploy._run_git")
    def test_status_falha(self, mock_git):
        mock_git.return_value = MagicMock(returncode=1, stdout="", stderr="git error")
        out = gd.executar_push_deploy_git(mensagem_commit="x")
        self.assertFalse(out["ok"])
        self.assertEqual(out["etapa"], "status")

    def test_branch_elegivel_respeita_protegidas_e_prefixos(self):
        self.assertFalse(
            gd._branch_elegivel_para_limpeza(
                "main",
                branch_atual="feature/x",
                protegidas=frozenset({"main"}),
                prefixos=("feature/",),
            )
        )
        self.assertTrue(
            gd._branch_elegivel_para_limpeza(
                "feature/foo",
                branch_atual="main",
                protegidas=frozenset({"main"}),
                prefixos=("feature/",),
            )
        )
        self.assertFalse(
            gd._branch_elegivel_para_limpeza(
                "release/1.0",
                branch_atual="main",
                protegidas=frozenset({"main"}),
                prefixos=("feature/",),
            )
        )

    @patch("core.git_deploy.deletar_branch_remota")
    @patch("core.git_deploy.listar_branches_locais_mergeadas", return_value=[])
    @patch("core.git_deploy.listar_branches_remotas_mergeadas", return_value=["feature/old"])
    @patch("core.git_deploy.fetch_remote", return_value={"ok": True})
    @patch("core.git_deploy.obter_branch_atual", return_value="main")
    def test_limpeza_deleta_remotas_mergeadas(self, _mock_atual, _mock_fetch, _mock_listar_r, _mock_listar_l, mock_del):
        mock_del.return_value = {"ok": True}
        out = gd.executar_limpeza_branches(
            prefixos=("feature/",),
            protegidas=frozenset({"main"}),
            limpar_locais=False,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["remotas_deletadas"], ["feature/old"])
        mock_del.assert_called_once_with("feature/old", remote="origin", cwd=None)

    @patch("core.git_deploy.listar_branches_remotas_mergeadas", return_value=["feature/x"])
    @patch("core.git_deploy.fetch_remote", return_value={"ok": True})
    @patch("core.git_deploy.obter_branch_atual", return_value="main")
    def test_limpeza_dry_run(self, _mock_atual, _mock_fetch, _mock_listar):
        out = gd.executar_limpeza_branches(prefixos=("feature/",), dry_run=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["remotas_planejadas"], ["feature/x"])
        self.assertEqual(out["remotas_deletadas"], [])

    @patch("core.git_deploy.push")
    @patch("core.git_deploy._run_git")
    @patch("core.git_deploy.fetch_remote", return_value={"ok": True})
    @patch("core.git_deploy.obter_status", return_value={"ok": True, "tem_alteracoes": False})
    def test_criar_branch_de_main(self, _mock_status, _mock_fetch, mock_git, mock_push):
        mock_git.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # checkout main
            MagicMock(returncode=0, stdout="", stderr=""),  # pull
            MagicMock(returncode=1, stdout="", stderr=""),  # rev-parse (não existe)
            MagicMock(returncode=0, stdout="", stderr=""),  # checkout -b
        ]
        out = gd.criar_branch_de_main("cursor/teste", push_upstream=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["criada"])
        mock_push.assert_called_once()


if __name__ == "__main__":
    unittest.main()
