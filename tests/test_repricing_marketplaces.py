import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.repricing.agente_repricing_marketplaces import executar


class RepricingMarketplacesTests(unittest.TestCase):
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.buscar_produto")
    def test_garante_lucro_minimo_10(self, mock_buscar_produto, _mock_alerta):
        mock_buscar_produto.return_value = {"sku": "SKU1", "custo": 9.5}
        produtos = [
            {
                "sku": "SKU1",
                "custo": 9.5,
                "canais": {
                    "mercadolivre": {"ativo": True, "item_id": "MLB1", "preco": 10.0, "preco_concorrente": 8.0}
                },
            }
        ]
        out = executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        self.assertEqual(out["total_ajustes"], 1)
        ajuste = out["ajustes"][0]
        self.assertGreaterEqual(ajuste["margem_pct"], 10.0)
        self.assertGreaterEqual(ajuste["novo_preco"], 10.0)

    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.buscar_produto")
    def test_nao_ajusta_sem_custo(self, mock_buscar_produto, _mock_alerta):
        mock_buscar_produto.return_value = {"sku": "SKU2", "custo": 0.0}
        produtos = [{"sku": "SKU2", "canais": {"shopee": {"ativo": True, "item_id": 1, "preco": 20.0}}}]
        out = executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        self.assertEqual(out["total_itens"], 0)
        self.assertEqual(out["total_ajustes"], 0)


if __name__ == "__main__":
    unittest.main()
