"""
tests/test_conectividade_marketplaces.py — agente de conectividade real (ML + Magalu).
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes import conectividade_marketplaces as agente


class TestAvaliarUm(unittest.TestCase):
    @patch.object(agente, "registrar_acesso")
    @patch.object(agente, "dias_sem_acesso", return_value=0)
    @patch("integracoes.ml.ml_client.probe_conexao", return_value={"ok": True, "status": 200, "msg": "autenticado"})
    def test_ml_ok_registra_acesso(self, _probe, _dias, mock_registrar):
        out = agente._avaliar_um("mercadolivre")
        self.assertTrue(out["ok"])
        self.assertEqual(out["status_http"], 200)
        mock_registrar.assert_called_once_with("mercadolivre")

    @patch.object(agente, "alertar_critico")
    @patch.object(agente, "registrar_acesso")
    @patch.object(agente, "dias_sem_acesso", return_value=2)
    @patch(
        "integracoes.ml.ml_client.probe_conexao",
        return_value={"ok": False, "status": 401, "msg": "token expirado ou inválido"},
    )
    def test_ml_falha_alerta_e_nao_registra_acesso(self, _probe, _dias, mock_registrar, mock_alerta):
        out = agente._avaliar_um("mercadolivre")
        self.assertFalse(out["ok"])
        self.assertEqual(out["status_http"], 401)
        mock_registrar.assert_not_called()
        mock_alerta.assert_called_once()
        self.assertIn("mercadolivre", mock_alerta.call_args.args[0])

    @patch.object(agente, "registrar_acesso")
    @patch.object(agente, "dias_sem_acesso", return_value=0)
    @patch(
        "integracoes.magalu.magalu_client.probe_conexao",
        return_value={"ok": True, "status": 200, "msg": "autenticado"},
    )
    def test_magalu_ok_registra_acesso(self, _probe, _dias, mock_registrar):
        out = agente._avaliar_um("magalu")
        self.assertTrue(out["ok"])
        mock_registrar.assert_called_once_with("magalu")

    def test_marketplace_desconhecido(self):
        out = agente._avaliar_um("shopee")
        # Shopee não está coberto por este agente (foco ML+Magalu) — não deve
        # quebrar, só reportar falha "marketplace desconhecido".
        self.assertFalse(out["ok"])


class TestExecutar(unittest.TestCase):
    @patch.object(agente, "_avaliar_um")
    def test_executar_agrega_resultado_dos_dois_marketplaces(self, mock_avaliar):
        mock_avaliar.side_effect = [
            {"marketplace": "mercadolivre", "ok": True, "status_http": 200, "msg": "", "dias_sem_acesso": 0},
            {"marketplace": "magalu", "ok": False, "status_http": 401, "msg": "x", "dias_sem_acesso": 3},
        ]
        out = agente.executar()
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["ok"], 1)
        self.assertEqual(out["falha"], 1)
        self.assertEqual(mock_avaliar.call_count, 2)

    @patch.object(agente, "incrementar")
    @patch.object(agente, "_avaliar_um", side_effect=RuntimeError("boom"))
    def test_excecao_inesperada_nao_propaga_e_segue_para_o_proximo(self, _mock_avaliar, mock_incrementar):
        out = agente.executar()
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["falha"], 2)
        self.assertEqual(out["ok"], 0)
        # incrementou métrica de falha por exceção pros dois marketplaces
        self.assertEqual(mock_incrementar.call_count, 2)


if __name__ == "__main__":
    unittest.main()
