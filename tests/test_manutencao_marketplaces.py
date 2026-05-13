"""
tests/test_manutencao_marketplaces.py — MAN01–MAN03
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes import manutencao_marketplaces as manut


class TestManutencaoMarketplaces(unittest.TestCase):
    @patch.object(manut, "keepalive_magalu")
    @patch.object(manut, "keepalive_shopee")
    def test_MAN01_executar_dois_resultados(self, mock_sh, mock_mg):
        mock_sh.return_value = {"ok": True, "acao": "já acessado hoje", "dias_sem_acesso": 0, "marketplace": "shopee"}
        mock_mg.return_value = {"ok": True, "acao": "já acessado hoje", "dias_sem_acesso": 0, "marketplace": "magalu"}
        out = manut.executar()
        self.assertIn("resultados", out)
        self.assertEqual(len(out["resultados"]), 2)

    @patch.object(manut, "alertar_gestor")
    @patch.object(manut, "keepalive_magalu")
    @patch.object(manut, "keepalive_shopee")
    def test_MAN02_alerta_keepalive_falha(self, mock_sh, mock_mg, mock_alert):
        mock_sh.return_value = {
            "ok": False,
            "acao": "falha no keepalive",
            "marketplace": "shopee",
            "dias_sem_acesso": 3,
            "alerta": True,
        }
        mock_mg.return_value = {"ok": True, "acao": "já acessado hoje", "dias_sem_acesso": 0, "marketplace": "magalu"}
        manut.executar()
        mock_alert.assert_called_once()

    @patch.object(manut, "keepalive_magalu")
    @patch.object(manut, "keepalive_shopee")
    def test_MAN03_passa_limite_dias(self, mock_sh, mock_mg):
        mock_sh.return_value = {"ok": True, "acao": "ok", "dias_sem_acesso": 0, "marketplace": "shopee"}
        mock_mg.return_value = {"ok": True, "acao": "ok", "dias_sem_acesso": 0, "marketplace": "magalu"}
        manut.executar(limite_dias_sem_acesso=7)
        mock_sh.assert_called_once_with(limite_dias_sem_acesso=7)
        mock_mg.assert_called_once_with(limite_dias_sem_acesso=7)


if __name__ == "__main__":
    unittest.main()
