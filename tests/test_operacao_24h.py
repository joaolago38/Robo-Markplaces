import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.operacao_24h import executar


class Operacao24hTests(unittest.TestCase):
    @patch("agentes.operacao_24h.alertar_gestor")
    @patch("agentes.operacao_24h._faturar_pedidos_lojahub")
    @patch("agentes.operacao_24h.executar_repricing_marketplaces")
    @patch("agentes.operacao_24h.executar_algoritmo_marketplaces")
    @patch("agentes.operacao_24h.listar_pedidos_prontos_faturar")
    @patch("agentes.operacao_24h.listar_resumo_vendas_24h")
    @patch("agentes.operacao_24h.listar_produtos")
    def test_operacao_24h_retorna_kpis(
        self,
        mock_produtos,
        mock_resumo,
        mock_pedidos,
        mock_algoritmo,
        mock_repricing,
        mock_faturar,
        _mock_alerta,
    ):
        mock_produtos.return_value = [{"sku": "A", "preco": 20, "custo": 10}]
        mock_resumo.return_value = {"ok": True, "data": {"receita": 200, "pedidos": 4}}
        mock_pedidos.return_value = [{"id": "1", "itens": [{"sku": "A", "quantidade": 2, "valor_unitario": 20}]}]
        mock_algoritmo.return_value = {"resumo": {"saudavel": 4, "atencao": 0, "critico": 0}, "marketplaces": {}}
        mock_repricing.return_value = {"total_ajustes": 1, "ajustes": []}
        mock_faturar.return_value = {"total": 1, "sucesso": 1, "falhas": 0, "itens": []}

        out = executar(dry_run_repricing=True, dry_run_nfe=False)
        self.assertIn("kpis_24h", out)
        self.assertEqual(out["kpis_24h"]["receita_24h"], 200.0)
        self.assertEqual(out["faturamento"]["sucesso"], 1)


if __name__ == "__main__":
    unittest.main()
