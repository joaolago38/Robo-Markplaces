"""
tests/test_conectividade_marketplaces.py — agente de conectividade real (4 MPs).
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
        self.assertIn("mercadolivre", mock_alerta.call_args.kwargs.get("chave", mock_alerta.call_args.args[0]))

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

    @patch.object(agente, "registrar_acesso")
    @patch.object(agente, "dias_sem_acesso", return_value=0)
    @patch(
        "integracoes.shopee.shopee_client.probe_conexao",
        return_value={"ok": True, "status": 200, "msg": "autenticado"},
    )
    def test_shopee_ok_registra_acesso(self, _probe, _dias, mock_registrar):
        out = agente._avaliar_um("shopee")
        self.assertTrue(out["ok"])
        mock_registrar.assert_called_once_with("shopee")

    @patch.object(agente, "alertar_critico")
    @patch.object(agente, "registrar_acesso")
    @patch.object(agente, "dias_sem_acesso", return_value=1)
    @patch(
        "integracoes.amazon.amazon_client.probe_conexao",
        return_value={"ok": False, "status": 403, "msg": "sem permissão"},
    )
    def test_amazon_falha_alerta_com_chave(self, _probe, _dias, mock_registrar, mock_alerta):
        out = agente._avaliar_um("amazon")
        self.assertFalse(out["ok"])
        mock_registrar.assert_not_called()
        mock_alerta.assert_called_once()
        self.assertEqual(mock_alerta.call_args.kwargs.get("chave"), "conectividade:amazon")

    def test_marketplace_desconhecido(self):
        out = agente._avaliar_um("lojahub")
        self.assertFalse(out["ok"])


class TestExecutar(unittest.TestCase):
    @patch.object(agente, "_avaliar_um")
    def test_executar_agrega_tres_marketplaces_sem_magalu_inativo(self, mock_avaliar):
        mock_avaliar.side_effect = [
            {"marketplace": "mercadolivre", "ok": True, "status_http": 200, "msg": "", "dias_sem_acesso": 0},
            {"marketplace": "shopee", "ok": True, "status_http": 200, "msg": "", "dias_sem_acesso": 0},
            {"marketplace": "amazon", "ok": False, "status_http": 0, "msg": "n/c", "dias_sem_acesso": 5},
        ]
        out = agente.executar()
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["ok"], 2)
        self.assertEqual(out["falha"], 1)
        self.assertEqual(mock_avaliar.call_count, 3)

    @patch.object(agente, "incrementar")
    @patch.object(agente, "_avaliar_um", side_effect=RuntimeError("boom"))
    def test_excecao_inesperada_nao_propaga(self, _mock_avaliar, mock_incrementar):
        out = agente.executar()
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["falha"], 3)
        self.assertEqual(out["ok"], 0)
        self.assertEqual(mock_incrementar.call_count, 3)


if __name__ == "__main__":
    unittest.main()
