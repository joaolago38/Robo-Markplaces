import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.faturamento.agente_faturamento import emitir_nfe_pedido


class FaturamentoTests(unittest.TestCase):
    @patch("agentes.faturamento.agente_faturamento.buscar_produto")
    def test_dry_run_monta_payload_com_ncm_catalogo(self, mock_buscar_produto):
        mock_buscar_produto.return_value = {"sku": "ESM-001", "nome": "Esmalte", "preco": 9.9}
        pedido = {
            "pedido_id": "PED-1",
            "cliente": {"nome": "Cliente Teste", "documento": "12345678901"},
            "itens": [{"sku": "ESM-001", "quantidade": 2}],
        }

        out = emitir_nfe_pedido(pedido, dry_run=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["dry_run"])
        item = out["payload_nfe"]["itens"][0]
        self.assertEqual(item["ncm"], "33041000")
        self.assertEqual(item["cfop"], "5102")
        self.assertEqual(item["csosn"], "102")
        self.assertIn("naturezaOperacao", out["payload_nfe"])

    @patch("agentes.faturamento.agente_faturamento.alertar_critico")
    @patch("agentes.faturamento.agente_faturamento.buscar_produto")
    def test_bloqueia_quando_sem_ncm(self, mock_buscar_produto, mock_alerta):
        mock_buscar_produto.return_value = {"sku": "SKU-SEM-NCM", "nome": "Produto", "preco": 10}
        pedido = {
            "pedido_id": "PED-2",
            "cliente": {"nome": "Cliente Teste"},
            "itens": [{"sku": "SKU-SEM-NCM", "quantidade": 1}],
        }
        out = emitir_nfe_pedido(pedido, dry_run=True)
        self.assertFalse(out["ok"])
        self.assertIn("sem NCM válido", out["erro"])
        mock_alerta.assert_called_once()


if __name__ == "__main__":
    unittest.main()
