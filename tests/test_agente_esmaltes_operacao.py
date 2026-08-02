"""tests/test_agente_esmaltes_operacao.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from agentes.esmaltes import agente_esmaltes_operacao as op


class TestEsmaltesOperacao(unittest.TestCase):
    def test_montar_mensagem_tem_secoes(self):
        msg = op.montar_mensagem_consolidada(
            crescimento={"ok": True, "mensagem": "KPI kits ok"},
            decisao={"ok": True, "mensagem": "FAZER publicar MLB"},
            ecossistema={"ok": True, "mensagem": "Plano 7d"},
        )
        self.assertIn("operação do dia", msg.lower())
        self.assertIn("Decisão do dia", msg)
        self.assertIn("Crescimento", msg)
        self.assertIn("Ecossistema", msg)
        self.assertIn("FAZER publicar MLB", msg)

    def test_montar_mensagem_falha_parcial(self):
        msg = op.montar_mensagem_consolidada(
            crescimento={"ok": False, "motivo": "agente_desligado"},
            decisao={"ok": True, "mensagem": "ok"},
            ecossistema=None,
        )
        self.assertIn("Falhou", msg)
        self.assertIn("ok", msg)

    @patch.object(op, "ESMALTES_OPERACAO_ATIVO", False)
    def test_desligado(self):
        out = op.executar(enviar_alerta=False)
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "agente_desligado")

    @patch.object(op, "alertar_gestor", return_value=True)
    @patch.object(op, "gestor_telegram_configurado", return_value=True)
    @patch.object(op, "pode_alertar_esmaltes", return_value=(True, "ok"))
    @patch.object(op, "escrever_json_atomico")
    @patch("agentes.esmaltes.agente_ecossistema_esmaltes.executar")
    @patch("agentes.esmaltes.agente_decisao_dia_esmaltes.executar")
    @patch("agentes.esmaltes.agente_crescimento_esmaltes.executar")
    def test_orquestra_sem_alerta_individual(
        self, mock_cre, mock_dia, mock_eco, _write, _pode, _gestor, mock_alerta
    ):
        mock_cre.return_value = {"ok": True, "mensagem": "cre", "kits_sem_mlb": 2}
        mock_dia.return_value = {"ok": True, "mensagem": "dia", "fazer": "x"}
        mock_eco.return_value = {"ok": True, "mensagem": "eco", "score_ecossistema": 70}

        out = op.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["partes_ok"], 3)
        mock_cre.assert_called_once_with(enviar_alerta=False)
        mock_dia.assert_called_once_with(enviar_alerta=False)
        mock_eco.assert_called_once_with(enviar_alerta=False)
        mock_alerta.assert_called_once()
        self.assertIn("cre", mock_alerta.call_args.args[0])
        self.assertEqual(mock_alerta.call_args.kwargs.get("agente_id"), "esmaltes_operacao")


if __name__ == "__main__":
    unittest.main()
