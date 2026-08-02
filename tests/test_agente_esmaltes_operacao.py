"""tests/test_agente_esmaltes_operacao.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from agentes.esmaltes import agente_esmaltes_operacao as op


class TestEsmaltesOperacao(unittest.TestCase):
    def test_card_decisao_primeiro(self):
        msg = op.montar_mensagem_consolidada(
            crescimento={
                "ok": True,
                "critico": True,
                "kits_sem_mlb": 3,
                "kpis": {"kits_pct_receita": 12, "kits_meta_ok": False, "margem_media_pct": 22, "margem_meta_ok": True},
                "checklist": [{"titulo": "Publicar kit rosa", "tipo": "mlb"}],
                "kits_sem_mlb_lista": [{"sku": "K1", "nome": "Kit Rosa"}],
                "mensagem": "ignorado no card estruturado",
            },
            decisao={
                "ok": True,
                "fazer_titulo": "Publicar MLB do kit líder",
                "fazer_detalhe": "Sem MLB não há venda",
                "nao_fazer_titulo": "Não impulsionar SKU bloqueado",
                "nao_fazer_detalhe": "Margem abaixo do piso",
                "custo_titulo": "Perde share na cor do mês",
                "liberados": 1,
                "bloqueados": 2,
                "skus_guerra": [{"sku": "S1", "papel": "guerra", "pode_impulsionar": False, "bloqueios": ["margem"]}],
                "kpis": {"kits_pct_receita": 12, "kits_meta_ok": False, "margem_media_pct": 22, "margem_meta_ok": True},
            },
            ecossistema={
                "ok": True,
                "score_ecossistema": 71,
                "cobertura_fontes_pct": 80,
                "top_7d": [{"titulo": "Combo removedor", "score": 90}],
            },
        )
        self.assertIn("AGIR AGORA", msg)
        self.assertIn("52.668.583/0001-27", msg)
        self.assertIn("FAZER:* Publicar MLB", msg)
        self.assertIn("NÃO FAZER", msg)
        self.assertIn("PANORAMA", msg)
        self.assertIn("PRÓXIMOS PASSOS", msg)
        self.assertIn("Publicar kit rosa", msg)
        self.assertIn("Combo removedor", msg)
        # ordem: AGIR antes de PANORAMA antes de PASSOS
        self.assertLess(msg.index("AGIR AGORA"), msg.index("PANORAMA"))
        self.assertLess(msg.index("PANORAMA"), msg.index("PRÓXIMOS PASSOS"))
        # não embute mensagem bruta dos filhos
        self.assertNotIn("ignorado no card estruturado", msg)

    def test_montar_mensagem_falha_parcial(self):
        msg = op.montar_mensagem_consolidada(
            crescimento={"ok": False, "motivo": "agente_desligado"},
            decisao={
                "ok": True,
                "fazer_titulo": "ok",
                "nao_fazer_titulo": "x",
            },
            ecossistema=None,
        )
        self.assertIn("FAZER:* ok", msg)
        self.assertIn("PRÓXIMOS PASSOS", msg)

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
        mock_cre.return_value = {
            "ok": True,
            "mensagem": "cre",
            "kits_sem_mlb": 2,
            "checklist": [],
            "kpis": {},
        }
        mock_dia.return_value = {
            "ok": True,
            "mensagem": "dia",
            "fazer": "x",
            "fazer_titulo": "Publicar",
            "nao_fazer_titulo": "Não ads",
        }
        mock_eco.return_value = {
            "ok": True,
            "mensagem": "eco",
            "score_ecossistema": 70,
            "top_7d": [],
            "acoes": [],
        }

        out = op.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["partes_ok"], 3)
        mock_cre.assert_called_once_with(enviar_alerta=False)
        mock_dia.assert_called_once_with(enviar_alerta=False)
        mock_eco.assert_called_once_with(enviar_alerta=False)
        mock_alerta.assert_called_once()
        body = mock_alerta.call_args.args[0]
        self.assertIn("AGIR AGORA", body)
        self.assertIn("Publicar", body)
        self.assertEqual(mock_alerta.call_args.kwargs.get("agente_id"), "esmaltes_operacao")


if __name__ == "__main__":
    unittest.main()
