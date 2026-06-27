"""
tests/test_robo_pausar_escrita.py
Kill switch global ROBO_PAUSAR_ESCRITA — bloqueio de escrita real.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import config, guardrails
from integracoes.bling import bling_client
from integracoes.ml import ml_client, ml_product_ads
from integracoes.magalu import magalu_client
from integracoes.shopee import shopee_client
from agentes.faturamento.agente_faturamento import emitir_nfe_pedido
from agentes.repricing.agente_repricing_marketplaces import executar as repricing_executar
from agentes.sincronizar_estoque_marketplaces import executar as estoque_executar
from agentes import operacao_24h


class TestBloqueioEscritaGlobal(unittest.TestCase):
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_bloqueio_ativo(self):
        out = guardrails.bloqueio_escrita_global()
        self.assertIsNotNone(out)
        self.assertFalse(out["ok"])
        self.assertIn("ROBO_PAUSAR_ESCRITA", out["erro"])

    @patch.object(config, "ROBO_PAUSAR_ESCRITA", False)
    def test_bloqueio_inativo(self):
        self.assertIsNone(guardrails.bloqueio_escrita_global())


class TestCriarNfe(unittest.TestCase):
    @patch.object(bling_client, "_request_bling")
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_kill_switch_bloqueia(self, mock_req):
        out = bling_client.criar_nfe({"itens": []})
        self.assertFalse(out["ok"])
        mock_req.assert_not_called()

    @patch.object(bling_client, "_request_bling")
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", False)
    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "tok")
    def test_sem_kill_switch_chama_api(self, mock_req):
        mock_req.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())
        mock_req.return_value.json.return_value = {"data": {"id": 1}}
        out = bling_client.criar_nfe({"itens": []})
        self.assertTrue(out["ok"])
        mock_req.assert_called_once()


class TestMlEstoqueEAnuncios(unittest.TestCase):
    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_atualizar_estoque_bloqueado(self, *_):
        self.assertFalse(ml_client.atualizar_estoque_item("MLB1", 5))

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_atualizar_preco_bloqueado(self, mock_req, *_):
        self.assertFalse(ml_client.atualizar_preco_item("MLB1", 5))
        mock_req.assert_not_called()

    @patch.object(ml_client, "_executar_acao_status")
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_pausar_anuncio_bloqueado(self, mock_exec):
        out = ml_client.pausar_anuncio("MLB1", dry_run=False, confirmar=True)
        self.assertFalse(out["ok"])
        mock_exec.assert_not_called()

    @patch.object(ml_client, "_executar_acao_status")
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_encerrar_anuncio_bloqueado(self, mock_exec):
        out = ml_client.encerrar_anuncio("MLB1", dry_run=False, confirmar=True)
        self.assertFalse(out["ok"])
        mock_exec.assert_not_called()

    @patch.object(ml_client, "_executar_acao_status", return_value={"ok": True, "dry_run": True})
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_pausar_dry_run_permitido(self, mock_exec):
        out = ml_client.pausar_anuncio("MLB1", dry_run=True)
        self.assertTrue(out["ok"])
        mock_exec.assert_called_once()


class TestMagaluShopeeEstoque(unittest.TestCase):
    @patch.object(magalu_client, "request")
    @patch.object(magalu_client, "_enabled", return_value=True)
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_magalu_estoque_bloqueado(self, mock_req, *_):
        self.assertFalse(magalu_client.atualizar_estoque_item("SKU1", 3))
        mock_req.assert_not_called()

    @patch.object(shopee_client, "request")
    @patch.object(shopee_client, "_enabled", return_value=True)
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_shopee_estoque_bloqueado(self, mock_req, *_):
        self.assertFalse(shopee_client.atualizar_estoque_item(99, 3))
        mock_req.assert_not_called()


class TestMlProductAdsGuardrails(unittest.TestCase):
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    @patch.object(ml_product_ads, "ML_ADS_KILL_SWITCH", False)
    def test_kill_switch_global_bloqueia_ads(self):
        out = ml_product_ads._guardrails_escrita(10.0)
        self.assertIsNotNone(out)
        self.assertIn("ROBO_PAUSAR_ESCRITA", out["erro"])

    @patch.object(ml_product_ads, "_request_ml")
    @patch.object(ml_product_ads, "_enabled", return_value=True)
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    @patch.object(ml_product_ads, "ML_ADS_KILL_SWITCH", False)
    def test_pausar_campanha_bloqueada(self, *_):
        out = ml_product_ads.pausar_campanha("C1", "MLB", dry_run=False, confirmar=True)
        self.assertFalse(out["ok"])


class TestAgentesEntrada(unittest.TestCase):
    @patch("core.guardrails.alertar_bloqueio_escrita_global")
    @patch("agentes.faturamento.agente_faturamento.buscar_produto")
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_emitir_nfe_bloqueado(self, mock_buscar, mock_alerta):
        mock_buscar.return_value = {"sku": "IMP-MIMO-003", "nome": "Kit", "preco": 10}
        out = emitir_nfe_pedido(
            {
                "pedido_id": "P1",
                "cliente": {"nome": "Cliente"},
                "itens": [{"sku": "IMP-MIMO-003", "quantidade": 1}],
            },
            dry_run=False,
        )
        self.assertFalse(out["ok"])
        mock_alerta.assert_called_once()

    @patch("core.guardrails.alertar_bloqueio_escrita_global")
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos", return_value=[])
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_repricing_bloqueado(self, *_):
        out = repricing_executar(dry_run=False)
        self.assertFalse(out["ok"])
        self.assertEqual(out["total_ajustes"], 0)

    @patch("core.guardrails.alertar_bloqueio_escrita_global")
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_sincronizar_estoque_bloqueado(self, *_):
        out = estoque_executar(produtos=[], dry_run=False)
        self.assertFalse(out["ok"])
        self.assertEqual(out["total_ajustes"], 0)

    @patch("core.guardrails.alertar_bloqueio_escrita_global")
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_operacao_24h_bloqueada(self, mock_alerta):
        out = operacao_24h.executar(dry_run_repricing=False, dry_run_nfe=True)
        self.assertFalse(out["ok"])
        self.assertTrue(out.get("bloqueado"))
        mock_alerta.assert_called_once()

    @patch("agentes.operacao_24h.alertar_gestor")
    @patch("agentes.operacao_24h._faturar_pedidos_lojahub", return_value={"total": 0, "sucesso": 0, "falhas": 0, "itens": []})
    @patch("agentes.operacao_24h.executar_repricing_marketplaces", return_value={"total_ajustes": 0})
    @patch("agentes.operacao_24h.executar_algoritmo_marketplaces", return_value={})
    @patch("agentes.operacao_24h.repricing_impala", return_value={})
    @patch("agentes.operacao_24h.verificar_gatilho_ads", return_value={})
    @patch("agentes.operacao_24h.verificar_alertas_esmaltes", return_value=[])
    @patch("agentes.operacao_24h.listar_produtos", return_value=[])
    @patch("agentes.operacao_24h.listar_resumo_vendas_24h", return_value={})
    @patch("agentes.operacao_24h.listar_pedidos_prontos_faturar", return_value=[])
    @patch.object(config, "ROBO_PAUSAR_ESCRITA", True)
    def test_operacao_24h_dry_run_total_permitido(self, *_):
        out = operacao_24h.executar(dry_run_repricing=True, dry_run_nfe=True)
        self.assertNotIn("bloqueado", out)


if __name__ == "__main__":
    unittest.main()
