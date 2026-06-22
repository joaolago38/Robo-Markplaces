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

    @patch("agentes.repricing.agente_repricing_marketplaces.buscar_menor_preco_concorrente")
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.buscar_produto")
    def test_busca_concorrente_ao_vivo_quando_ausente(
        self, mock_buscar_produto, _mock_alerta, mock_vivo
    ):
        """Sem preco_concorrente no payload (ML), deve buscar ao vivo."""
        mock_buscar_produto.return_value = {"sku": "SKU3", "custo": 9.5}
        mock_vivo.return_value = 30.0
        produtos = [
            {
                "sku": "SKU3",
                "custo": 9.5,
                "canais": {
                    "mercadolivre": {"ativo": True, "item_id": "MLB3", "preco": 10.0}
                },
            }
        ]
        out = executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        mock_vivo.assert_called_once_with("MLB3")
        ajuste = out["ajustes"][0]
        self.assertEqual(ajuste["fonte_concorrente"], "ao_vivo")
        self.assertIn("economia_estimada_piso_margem", out)
        self.assertGreaterEqual(out["economia_estimada_piso_margem"], 0.0)

    @patch("agentes.repricing.agente_repricing_marketplaces.buscar_menor_preco_concorrente")
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.buscar_produto")
    def test_nao_busca_ao_vivo_quando_payload_tem_preco(
        self, mock_buscar_produto, _mock_alerta, mock_vivo
    ):
        """Com preco_concorrente no payload, NÃO chama a busca ao vivo."""
        mock_buscar_produto.return_value = {"sku": "SKU4", "custo": 9.5}
        produtos = [
            {
                "sku": "SKU4",
                "custo": 9.5,
                "canais": {
                    "mercadolivre": {
                        "ativo": True,
                        "item_id": "MLB4",
                        "preco": 10.0,
                        "preco_concorrente": 25.0,
                    }
                },
            }
        ]
        out = executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        mock_vivo.assert_not_called()
        self.assertEqual(out["ajustes"][0]["fonte_concorrente"], "payload")


if __name__ == "__main__":
    unittest.main()
