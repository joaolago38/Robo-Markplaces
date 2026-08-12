"""tests/test_metricas_pontos_cegos.py — chat/nfe/estoque/telegram/repricing/ads/vendas."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestChatMetricas(unittest.TestCase):
    @patch("agentes.ml.agente_ml.incrementar")
    @patch("agentes.ml.agente_ml.gauge")
    @patch("agentes.ml.agente_ml.responder", return_value=True)
    @patch("agentes.ml.agente_ml.responder_chat", return_value="oi")
    @patch("agentes.ml.agente_ml.tentar_claim", return_value=True)
    @patch("agentes.ml.agente_ml.carregar_contexto_fechamento_ml", return_value={})
    @patch("agentes.ml.agente_ml.buscar_perguntas", return_value=[{"id": "1", "text": "tem frete?"}])
    @patch("agentes.ml.agente_ml._montar_produto_resposta", return_value={"nome": "Kit", "preco": 10})
    @patch("agentes.ml.agente_ml.time.sleep")
    @patch("agentes.ml.agente_ml.escrever_json_atomico")
    def test_chat_incrementa_respondidas(self, *_):
        from agentes.ml import agente_ml as ml

        with patch.dict(
            "sys.modules",
            {
                "integracoes.social.conversao_manicures": MagicMock(
                    pergunta_parece_manicure=MagicMock(return_value=False),
                    resposta_chat_ml_haiku=MagicMock(),
                )
            },
        ):
            out = ml.ciclo_chat()
        self.assertEqual(out, 1)
        nomes = [c.args[0] for c in ml.incrementar.call_args_list]
        self.assertIn("chat.respondidas", nomes)
        self.assertIn("chat.rodadas", nomes)


class TestChatShopeeMetricas(unittest.TestCase):
    @patch("agentes.shopee.agente_shopee.escrever_json_atomico")
    @patch("agentes.shopee.agente_shopee.incrementar")
    @patch("agentes.shopee.agente_shopee.gauge")
    @patch("agentes.shopee.agente_shopee.time.sleep")
    @patch("agentes.shopee.agente_shopee.responder_pergunta", return_value=True)
    @patch("agentes.shopee.agente_shopee.responder_chat", return_value="ok")
    @patch("agentes.shopee.agente_shopee.buscar_produto", return_value={})
    @patch(
        "agentes.shopee.agente_shopee.listar_perguntas_nao_respondidas",
        return_value=[{"item_id": "1", "comment_id": "c1", "comment": "tem estoque?"}],
    )
    def test_shopee_chat_metricas(self, *_mocks):
        from agentes.shopee import agente_shopee as sh

        self.assertEqual(sh.responder_perguntas(), 1)
        nomes = [c.args[0] for c in sh.incrementar.call_args_list]
        self.assertIn("chat.respondidas", nomes)
        self.assertIn("chat.rodadas", nomes)


class TestNfeMetricas(unittest.TestCase):
    @patch("agentes.faturamento.agente_faturamento.incrementar")
    def test_dry_run_conta_dry_run(self, mock_inc):
        from agentes.faturamento.agente_faturamento import emitir_nfe_pedido

        with patch(
            "agentes.faturamento.agente_faturamento._montar_itens_nfe",
            return_value=([{"codigo": "1"}], []),
        ), patch(
            "agentes.faturamento.agente_faturamento._montar_contato",
            return_value={},
        ):
            out = emitir_nfe_pedido(
                {
                    "pedido_id": "P1",
                    "cliente": {"nome": "A", "documento": "1"},
                    "itens": [{"sku": "X", "quantidade": 1, "valor_unitario": 10}],
                },
                dry_run=True,
            )
        self.assertTrue(out["ok"])
        mock_inc.assert_any_call("nfe.dry_run")


class TestTelegramMetricas(unittest.TestCase):
    @patch("core.notificador.incrementar", create=True)
    @patch("core.notificador.request")
    @patch("core.notificador.pode_enviar", return_value=True)
    @patch("core.notificador.TELEGRAM_CHAT_ID", "123")
    @patch("core.notificador.TELEGRAM_TOKEN", "tok")
    def test_envio_ok_conta_metrica(self, mock_req, *_):
        import core.notificador as n

        mock_req.return_value = MagicMock(status_code=200)
        mock_req.return_value.raise_for_status = MagicMock()
        with patch("core.datadog_metrics.incrementar") as mock_inc:
            self.assertTrue(n.alertar("oi", _ignorar_cooldown=True))
            nomes = [c.args[0] for c in mock_inc.call_args_list]
            self.assertIn("telegram.envio_ok", nomes)


class TestEstoqueHeartbeat(unittest.TestCase):
    def test_heartbeat_gravado(self):
        from agentes import sincronizar_estoque_marketplaces as est

        with tempfile.TemporaryDirectory() as tmp:
            hb = Path(tmp) / "estoque_ultima.json"
            with patch.object(est, "HEARTBEAT_PATH", hb), patch.object(
                est, "_carregar_catalogo", return_value=[]
            ), patch.object(
                est, "probe_produtos", return_value={"ok": True, "status": 200, "msg": "ok"}
            ), patch.object(
                est, "listar_produtos_por_sku_detalhado", return_value=({}, True)
            ), patch(
                "agentes.sincronizar_estoque_marketplaces.incrementar"
            ):
                out = est.executar(produtos=[], dry_run=True)
            self.assertEqual(out["total_ajustes"], 0)
            self.assertTrue(hb.exists())


class TestAdsMetricas(unittest.TestCase):
    @patch("agentes.ml.agente_ads_gatilho.escrever_json_atomico")
    @patch("agentes.ml.agente_ads_gatilho.gauge")
    @patch("agentes.ml.agente_ads_gatilho.incrementar")
    def test_metricas_e_heartbeat(self, mock_inc, mock_gauge, _hb):
        from agentes.ml.agente_ads_gatilho import _metricas_e_heartbeat

        _metricas_e_heartbeat(
            {
                "decisao": "aguardar",
                "budget_sugerido_dia": 0,
                "acos_atual": 0.1,
                "avaliacoes": 5,
                "confirmado_gestor": None,
            }
        )
        nomes = [c.args[0] for c in mock_inc.call_args_list]
        self.assertIn("ads.rodadas", nomes)
        self.assertTrue(mock_gauge.called)


class TestVendasMetricas(unittest.TestCase):
    @patch("agentes.vendas_notificador.incrementar")
    def test_falha_whatsapp_conta(self, mock_inc):
        from agentes.vendas_notificador import _notificar_novos_pedidos

        with patch("agentes.vendas_notificador.notificar_venda", return_value=False):
            novos = _notificar_novos_pedidos(
                "mercadolivre",
                [{"order_id": "O1", "total": 10, "itens": [{"sku": "X", "quantidade": 1}]}],
                set(),
            )
        self.assertEqual(novos, set())
        mock_inc.assert_any_call("vendas.falha_whatsapp", tags=["marketplace:mercadolivre"])


class TestMetaMetricas(unittest.TestCase):
    @patch("agentes.social.agente_metricas_meta.alertar_gestor")
    @patch("agentes.social.agente_metricas_meta.gauge")
    @patch("agentes.social.agente_metricas_meta.incrementar")
    @patch(
        "agentes.social.agente_metricas_meta.listar_metricas_campanhas",
        return_value=[],
    )
    def test_meta_rodadas(self, *_mocks):
        from agentes.social import agente_metricas_meta as meta

        out = meta.executar()
        self.assertEqual(out["resumo"]["total"], 0)
        nomes = [c.args[0] for c in meta.incrementar.call_args_list]
        self.assertIn("meta.rodadas", nomes)


class TestVigiaFiltrosNotificador(unittest.TestCase):
    def test_notificador_nao_esta_em_ignorar(self):
        from integracoes.datadog import vigia_saude as vs

        filtros = vs.carregar_filtros_erro("catalogo/datadog_vigia_filtros.json")
        self.assertNotIn("notificador", filtros.get("loggers_ignorar") or [])
        self.assertIn("notificador", filtros.get("loggers_ml") or [])
        self.assertIn("agente_faturamento", filtros.get("loggers_ml") or [])

    def test_fonte_estoque_no_catalogo(self):
        from integracoes.datadog import vigia_saude as vs

        fontes = vs.carregar_fontes("catalogo/datadog_vigia_fontes.json")
        ids = {f.get("id") for f in fontes}
        self.assertIn("estoque", ids)
        self.assertIn("ads_gatilho", ids)
        self.assertIn("chat", ids)
        self.assertIn("nfe", ids)
        self.assertIn("vendas_whatsapp", ids)


if __name__ == "__main__":
    unittest.main()
