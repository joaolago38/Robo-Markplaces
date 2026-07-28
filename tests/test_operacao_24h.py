import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.operacao_24h import (
    _fallback_resumo_operacao,
    _payload_para_contexto_claude,
    _sintetizar_claude_operacao,
    executar,
)
from core.config import ACOS_MAXIMO

_PAYLOAD_MIN = {
    "kpis_24h": {"receita_24h": 100},
    "marketplaces": {"resumo": {"saudavel": 2, "atencao": 1, "critico": 0}, "marketplaces": {}},
    "gatilho_ads": {"decisao": "aguardar", "motivos": []},
    "alertas_esmaltes": [],
    "repricing": {"total_ajustes": 0},
}


class TestSintetizarOperacao24h(unittest.TestCase):
    def test_payload_para_contexto_inclui_kpis(self):
        ctx = _payload_para_contexto_claude(_PAYLOAD_MIN)
        self.assertEqual(ctx["kpis_24h"]["receita_24h"], 100)

    @patch("core.resumo_ia.cfg.ANTHROPIC_API_KEY", "")
    def test_fallback_sem_api_key(self, *_):
        payload = {
            **_PAYLOAD_MIN,
            "marketplaces": {"resumo": {"saudavel": 2, "atencao": 0, "critico": 0}, "marketplaces": {}},
        }
        out = _sintetizar_claude_operacao(payload)
        self.assertEqual(out, _fallback_resumo_operacao(payload))

    @patch("core.resumo_ia.perguntar", return_value="⚠️ Erro na IA")
    @patch("core.resumo_ia.cfg.ANTHROPIC_API_KEY", "sk-test")
    def test_fallback_quando_perguntar_retorna_erro(self, *_):
        out = _sintetizar_claude_operacao(_PAYLOAD_MIN)
        self.assertEqual(out, _fallback_resumo_operacao(_PAYLOAD_MIN))

    @patch("core.resumo_ia.perguntar", return_value="Receita em risco por ACOS alto.")
    @patch("core.resumo_ia.cfg.ANTHROPIC_API_KEY", "sk-test")
    def test_chama_perguntar_com_contexto(self, mock_perguntar):
        payload = {
            **_PAYLOAD_MIN,
            "marketplaces": {
                "resumo": {"critico": 1},
                "marketplaces": {"mercadolivre": {"status": "critico", "score": 40}},
            },
        }
        out = _sintetizar_claude_operacao(payload)
        self.assertIn("ACOS", out)
        mock_perguntar.assert_called_once()
        ctx_passado = mock_perguntar.call_args.kwargs.get("contexto") or mock_perguntar.call_args[1].get("contexto")
        self.assertIn("kpis_24h", ctx_passado)


class Operacao24hTests(unittest.TestCase):
    @patch("agentes.operacao_24h.alertar_gestor")
    @patch("agentes.operacao_24h._faturar_pedidos_lojahub")
    @patch("agentes.operacao_24h.executar_repricing_marketplaces")
    @patch("agentes.operacao_24h.executar_algoritmo_marketplaces")
    @patch("agentes.operacao_24h.repricing_impala")
    @patch("agentes.operacao_24h.verificar_alertas_esmaltes")
    @patch("agentes.operacao_24h.verificar_gatilho_ads")
    @patch("agentes.operacao_24h.listar_pedidos_prontos_faturar")
    @patch("agentes.operacao_24h.listar_resumo_vendas_24h")
    @patch("agentes.operacao_24h.listar_produtos")
    def test_operacao_24h_retorna_kpis(
        self,
        mock_produtos,
        mock_resumo,
        mock_pedidos,
        mock_gatilho,
        _mock_alertas,
        mock_repricing_impala,
        mock_algoritmo,
        mock_repricing,
        mock_faturar,
        mock_alerta,
    ):
        mock_produtos.return_value = [{"sku": "A", "preco": 20, "custo": 10}]
        mock_resumo.return_value = {"ok": True, "data": {"receita": 200, "pedidos": 4}}
        mock_pedidos.return_value = [{"id": "1", "itens": [{"sku": "A", "quantidade": 2, "valor_unitario": 20}]}]
        mock_algoritmo.return_value = {"resumo": {"saudavel": 4, "atencao": 0, "critico": 0}, "marketplaces": {}}
        mock_repricing.return_value = {"total_ajustes": 1, "ajustes": []}
        mock_faturar.return_value = {"total": 1, "sucesso": 1, "falhas": 0, "itens": []}
        mock_repricing_impala.return_value = {}
        mock_gatilho.return_value = {"decisao": "aguardar", "motivos": []}
        _mock_alertas.return_value = []

        out = executar(dry_run_repricing=True, dry_run_nfe=True)
        self.assertIn("kpis_24h", out)
        self.assertEqual(out["kpis_24h"]["receita_24h"], 200.0)
        self.assertEqual(out["faturamento"]["sucesso"], 1)
        self.assertTrue(out["modo"]["nfe_dry_run"])
        msg = mock_alerta.call_args[0][0]
        self.assertIn("Resumo IA", msg)

    @patch("agentes.operacao_24h.alertar_gestor")
    @patch("agentes.operacao_24h._faturar_pedidos_lojahub")
    @patch("agentes.operacao_24h.executar_repricing_marketplaces")
    @patch("agentes.operacao_24h.executar_algoritmo_marketplaces")
    @patch("agentes.operacao_24h.repricing_impala")
    @patch("agentes.operacao_24h.verificar_alertas_esmaltes")
    @patch("agentes.operacao_24h.listar_pedidos_prontos_faturar")
    @patch("agentes.operacao_24h.listar_resumo_vendas_24h")
    @patch("agentes.operacao_24h.listar_produtos")
    @patch("agentes.operacao_24h.listar_campanhas")
    @patch("integracoes.ml.ml_client.buscar_reputacao_vendedor")
    @patch("agentes.operacao_24h.verificar_gatilho_ads")
    def test_acos_agregado_alimenta_gatilho_pausar(
        self,
        mock_gatilho,
        mock_reputacao,
        mock_campanhas,
        mock_produtos,
        mock_resumo,
        mock_pedidos,
        _mock_alertas,
        mock_repricing_impala,
        mock_algoritmo,
        mock_repricing,
        mock_faturar,
        _mock_alerta,
    ):
        mock_produtos.return_value = []
        mock_resumo.return_value = {"ok": False, "data": {}}
        mock_pedidos.return_value = []
        _mock_alertas.return_value = []
        mock_repricing_impala.return_value = {}
        mock_algoritmo.return_value = {"resumo": {}, "marketplaces": {}}
        mock_repricing.return_value = {"total_ajustes": 0, "ajustes": []}
        mock_faturar.return_value = {"total": 0, "sucesso": 0, "falhas": 0, "itens": []}
        mock_reputacao.return_value = {
            "metrics": {
                "total_ratings": 30,
                "average_rating": 4.9,
                "power_seller_status": "gold",
            }
        }
        mock_campanhas.return_value = [
            {"id": "C1", "acos": 0.35, "cost": 100},
            {"id": "C2", "acos": 0.10, "cost": 50},
        ]
        mock_gatilho.return_value = {"decisao": "pausar", "acos_atual": 0.2667}

        executar(dry_run_repricing=True, dry_run_nfe=True)

        acos_esperado = (0.35 * 100 + 0.10 * 50) / 150
        mock_gatilho.assert_called_once()
        acos_passado = mock_gatilho.call_args.kwargs.get("acos_atual")
        self.assertAlmostEqual(acos_passado, acos_esperado, places=4)
        self.assertGreater(acos_passado, ACOS_MAXIMO)

    @patch("agentes.operacao_24h.emitir_nfe_pedido")
    @patch("agentes.operacao_24h.listar_pedidos_prontos_faturar")
    def test_faturar_default_dry_run(self, mock_pedidos, mock_emitir):
        from agentes.operacao_24h import _faturar_pedidos_lojahub

        mock_pedidos.return_value = [{"id": "1", "itens": [{"sku": "A", "quantidade": 1, "valor_unitario": 10}]}]
        mock_emitir.return_value = {"ok": True, "dry_run": True}
        _faturar_pedidos_lojahub()
        mock_emitir.assert_called_once()
        self.assertTrue(mock_emitir.call_args[1]["dry_run"])

if __name__ == "__main__":
    unittest.main()
