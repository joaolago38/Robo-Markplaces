"""
tests/test_agente_push_deploy.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.orquestrador import agente_push_deploy as deploy


class AgentePushDeployTests(unittest.TestCase):
    @patch("agentes.orquestrador.agente_push_deploy.executar_sync_push_main")
    @patch("agentes.orquestrador.agente_push_deploy.executar_push_deploy_git")
    @patch("agentes.orquestrador.agente_push_deploy._preflight_qualidade")
    def test_fluxo_completo(self, mock_pre, mock_git, mock_sync):
        mock_pre.return_value = {"ok": True, "etapas": [], "falhas": 0}
        mock_git.return_value = {"ok": True, "push_enviado": True, "branch": "main"}
        mock_sync.return_value = {"ok": True, "falhas": 0}
        out = deploy.executar(mensagem_commit="teste deploy")
        self.assertTrue(out["ok"])
        mock_git.assert_called_once()
        mock_sync.assert_called_once()

    @patch("agentes.orquestrador.agente_push_deploy.executar_sync_push_main")
    @patch("agentes.orquestrador.agente_push_deploy._preflight_qualidade")
    def test_sem_push_so_agentes(self, mock_pre, mock_sync):
        mock_pre.return_value = {"ok": True, "etapas": [], "falhas": 0}
        mock_sync.return_value = {"ok": True, "falhas": 0}
        with patch("agentes.orquestrador.agente_push_deploy.obter_status", return_value={"ok": True}):
            out = deploy.executar(pular_push=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["git"].get("pulado"))

    @patch("agentes.orquestrador.agente_push_deploy.alertar_gestor")
    @patch("agentes.orquestrador.agente_push_deploy.gestor_telegram_configurado", return_value=True)
    @patch("agentes.orquestrador.agente_push_deploy._preflight_qualidade")
    def test_aborta_se_preflight_falha(self, mock_pre, _mock_tg, mock_alerta):
        mock_pre.return_value = {"ok": False, "etapas": [{"ok": False}], "falhas": 1}
        out = deploy.executar()
        self.assertFalse(out["ok"])
        mock_alerta.assert_called_once()

    @patch("agentes.orquestrador.agente_push_deploy.executar_sync_push_main")
    @patch("agentes.orquestrador.agente_push_deploy.executar_push_deploy_git")
    def test_falha_git(self, mock_git, mock_sync):
        mock_git.return_value = {"ok": False, "etapa": "push", "erro": "rejected"}
        out = deploy.executar(pular_qualidade=True, pular_agentes=True)
        self.assertFalse(out["ok"])
        mock_sync.assert_not_called()

    @patch("agentes.orquestrador.agente_push_deploy.executar_sync_push_main")
    @patch("agentes.orquestrador.agente_push_deploy.executar_push_deploy_git")
    def test_git_sem_push_motivo(self, mock_git, mock_sync):
        mock_git.return_value = {"ok": True, "motivo": "nenhuma alteração"}
        mock_sync.return_value = {"ok": True, "falhas": 0}
        out = deploy.executar(pular_qualidade=True)
        self.assertTrue(out["ok"])

    @patch("agentes.orquestrador.agente_push_deploy.executar_sync_push_main")
    @patch("agentes.orquestrador.agente_push_deploy.executar_push_deploy_git")
    def test_agentes_com_falhas(self, mock_git, mock_sync):
        mock_git.return_value = {"ok": True, "push_enviado": True}
        mock_sync.return_value = {"ok": False, "falhas": 2}
        out = deploy.executar(pular_qualidade=True)
        self.assertFalse(out["ok"])

    @patch("agentes.orquestrador.agente_push_deploy.executar_push_deploy_git")
    def test_mensagem_commit_padrao(self, mock_git):
        mock_git.return_value = {"ok": True, "motivo": "nada"}
        out = deploy.executar(mensagem_commit="", pular_qualidade=True, pular_agentes=True)
        self.assertTrue(out["ok"])
        self.assertIn("deploy automático", mock_git.call_args.kwargs["mensagem_commit"])

    @patch("subprocess.run")
    def test_rodar_comando_ok(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        out = deploy._rodar_comando(["echo", "hi"], descricao="echo")
        self.assertTrue(out["ok"])

    @patch("subprocess.run", side_effect=OSError("boom"))
    def test_rodar_comando_excecao(self, _mock_run):
        out = deploy._rodar_comando(["x"], descricao="fail")
        self.assertFalse(out["ok"])
        self.assertIn("boom", out["erro"])

    @patch("agentes.orquestrador.agente_push_deploy._rodar_comando")
    def test_preflight_qualidade(self, mock_cmd):
        mock_cmd.return_value = {"ok": True}
        out = deploy._preflight_qualidade(rodar_testes=True, rodar_ruff=True)
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["etapas"]), 2)

    @patch("agentes.orquestrador.agente_push_deploy.executar")
    def test_main_sucesso(self, mock_exec):
        mock_exec.return_value = {"ok": True, "git": {"push_enviado": True}, "agentes": {"falhas": 0}}
        self.assertEqual(deploy.main([]), 0)

    @patch("agentes.orquestrador.agente_push_deploy.executar")
    def test_main_falha(self, mock_exec):
        mock_exec.return_value = {"ok": False, "git": {}, "agentes": {"falhas": 1}}
        self.assertEqual(deploy.main(["--sem-preflight"]), 1)


if __name__ == "__main__":
    unittest.main()
