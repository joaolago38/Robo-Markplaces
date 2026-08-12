"""
tests/test_falha_aplicacao_real_vs_decidida.py
Cobertura dedicada ao ponto cego corrigido em agente_repricing_marketplaces
e sincronizar_estoque_marketplaces: "ajuste detectado/decidido" não é o
mesmo que "ajuste aplicado com sucesso" — antes desta correção, quando a
chamada de escrita ao marketplace falhava (ex.: atualizar_preco_item
retornando False), o agente contava como se tivesse aplicado, e o
alerta ao gestor dizia "N ajustes aplicados" mesmo quando alguns
falharam silenciosamente.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.repricing.agente_repricing_marketplaces import executar as executar_repricing
from agentes.sincronizar_estoque_marketplaces import executar as executar_estoque


class TestRepricingDistingueFalhaDeSucesso(unittest.TestCase):
    @patch("core.algoritmo_eventos.deve_congelar_repricing", return_value=(False, ""))
    @patch("agentes.repricing.agente_repricing_marketplaces.incrementar")
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_critico")
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.atualizar_preco_ml", return_value=False)
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos_por_sku")
    def test_falha_na_api_nao_conta_como_aplicado(
        self, mock_listar_bling, _mock_atualizar, mock_alertar_gestor, mock_alertar_critico, mock_incrementar, _cong
    ):
        mock_listar_bling.return_value = {"SKU1": {"sku": "SKU1", "custo": 9.5}}
        produtos = [
            {
                "sku": "SKU1",
                "custo": 9.5,
                "canais": {
                    "mercadolivre": {"ativo": True, "item_id": "MLB1", "preco": 10.0, "preco_concorrente": 8.0}
                },
            }
        ]
        out = executar_repricing(produtos=produtos, dry_run=False, lucro_minimo_pct=10.0)

        self.assertEqual(out["total_ajustes"], 1)
        self.assertEqual(out["total_aplicados_sucesso"], 0)
        self.assertEqual(out["total_falhas_aplicacao"], 1)
        self.assertTrue(out["ajustes"][0]["falhou_aplicacao"])

        # Alerta crítico específico de falha de aplicação foi disparado.
        mock_alertar_critico.assert_called_once()
        self.assertIn("FALHARAM", mock_alertar_critico.call_args.args[0])

        # Métrica de falha foi enviada ao Datadog.
        mock_incrementar.assert_any_call("repricing.falha_aplicacao", tags=["canal:mercadolivre"])

        # O alerta normal ao gestor reflete o resultado real (0/1), não "1 aplicado".
        mensagem_gestor = mock_alertar_gestor.call_args.args[0]
        self.assertIn("0/1", mensagem_gestor)

    @patch("core.algoritmo_eventos.deve_congelar_repricing", return_value=(False, ""))
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_critico")
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.atualizar_preco_ml", return_value=True)
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos_por_sku")
    def test_sucesso_real_conta_corretamente_e_nao_alerta_falha(
        self, mock_listar_bling, _mock_atualizar, mock_alertar_gestor, mock_alertar_critico, _cong
    ):
        mock_listar_bling.return_value = {"SKU1": {"sku": "SKU1", "custo": 9.5}}
        produtos = [
            {
                "sku": "SKU1",
                "custo": 9.5,
                "canais": {
                    "mercadolivre": {"ativo": True, "item_id": "MLB1", "preco": 10.0, "preco_concorrente": 8.0}
                },
            }
        ]
        out = executar_repricing(produtos=produtos, dry_run=False, lucro_minimo_pct=10.0)

        self.assertEqual(out["total_ajustes"], 1)
        self.assertEqual(out["total_aplicados_sucesso"], 1)
        self.assertEqual(out["total_falhas_aplicacao"], 0)
        mock_alertar_critico.assert_not_called()
        self.assertIn("1/1", mock_alertar_gestor.call_args.args[0])

    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos_por_sku")
    def test_dry_run_continua_so_detectando_sem_contar_falha(self, mock_listar_bling, mock_alertar_gestor):
        mock_listar_bling.return_value = {"SKU1": {"sku": "SKU1", "custo": 9.5}}
        produtos = [
            {
                "sku": "SKU1",
                "custo": 9.5,
                "canais": {
                    "mercadolivre": {"ativo": True, "item_id": "MLB1", "preco": 10.0, "preco_concorrente": 8.0}
                },
            }
        ]
        out = executar_repricing(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)

        self.assertEqual(out["total_ajustes"], 1)
        self.assertEqual(out["total_aplicados_sucesso"], 0)
        self.assertEqual(out["total_falhas_aplicacao"], 0)
        self.assertIn("detectados", mock_alertar_gestor.call_args.args[0])


class TestEstoqueDistingueFalhaDeSucesso(unittest.TestCase):
    @patch("agentes.sincronizar_estoque_marketplaces.incrementar")
    @patch("agentes.sincronizar_estoque_marketplaces.alertar_critico")
    @patch("agentes.sincronizar_estoque_marketplaces.alertar_gestor")
    @patch.dict(
        "agentes.sincronizar_estoque_marketplaces._CANAIS_ESTOQUE",
        {"mercadolivre": lambda ref, estoque: False},
    )
    @patch(
        "agentes.sincronizar_estoque_marketplaces.listar_produtos_por_sku_detalhado",
        return_value=({"SKU1": {"sku": "SKU1", "estoque": 50}}, True),
    )
    @patch(
        "agentes.sincronizar_estoque_marketplaces.probe_produtos",
        return_value={"ok": True, "status": 200, "msg": "ok"},
    )
    def test_falha_na_api_nao_conta_como_aplicado(
        self, _probe, _mock_listar_bling, mock_alertar_gestor, mock_alertar_critico, mock_incrementar
    ):
        produtos = [
            {
                "sku": "SKU1",
                "canais": {
                    "mercadolivre": {"ativo": True, "item_id": "MLB123456", "estoque": 10}
                },
            }
        ]
        out = executar_estoque(produtos=produtos, dry_run=False)

        self.assertEqual(out["total_ajustes"], 1)
        self.assertEqual(out["total_aplicados_sucesso"], 0)
        self.assertEqual(out["total_falhas_aplicacao"], 1)
        self.assertTrue(out["ajustes"][0]["falhou_aplicacao"])

        mock_alertar_critico.assert_called()
        self.assertTrue(
            any("FALHARAM" in str(c.args[0]) for c in mock_alertar_critico.call_args_list)
        )
        mock_incrementar.assert_any_call("estoque.falha_aplicacao", tags=["canal:mercadolivre"])

        mensagem_gestor = mock_alertar_gestor.call_args.args[0]
        self.assertIn("0/1", mensagem_gestor)

    @patch("agentes.sincronizar_estoque_marketplaces.alertar_critico")
    @patch("agentes.sincronizar_estoque_marketplaces.alertar_gestor")
    @patch.dict(
        "agentes.sincronizar_estoque_marketplaces._CANAIS_ESTOQUE",
        {"mercadolivre": lambda ref, estoque: True},
    )
    @patch("agentes.sincronizar_estoque_marketplaces._salvar_catalogo")
    @patch(
        "agentes.sincronizar_estoque_marketplaces.listar_produtos_por_sku_detalhado",
        return_value=({"SKU1": {"sku": "SKU1", "estoque": 50}}, True),
    )
    @patch(
        "agentes.sincronizar_estoque_marketplaces.probe_produtos",
        return_value={"ok": True, "status": 200, "msg": "ok"},
    )
    def test_sucesso_real_conta_corretamente_e_nao_alerta_falha(
        self, _probe, _mock_listar_bling, _mock_salvar_catalogo, mock_alertar_gestor, mock_alertar_critico
    ):
        produtos = [
            {
                "sku": "SKU1",
                "canais": {
                    "mercadolivre": {"ativo": True, "item_id": "MLB123456", "estoque": 10}
                },
            }
        ]
        out = executar_estoque(produtos=produtos, dry_run=False)

        self.assertEqual(out["total_ajustes"], 1)
        self.assertEqual(out["total_aplicados_sucesso"], 1)
        self.assertEqual(out["total_falhas_aplicacao"], 0)
        # Pode alertar placeholder/saldo — só não deve alertar FALHARAM
        for c in mock_alertar_critico.call_args_list:
            self.assertNotIn("FALHARAM", str(c.args[0]))
        self.assertIn("1/1", mock_alertar_gestor.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
