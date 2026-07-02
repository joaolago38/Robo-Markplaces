import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.repricing import agente_repricing_marketplaces as repricing


class RepricingMarketplacesTests(unittest.TestCase):
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos_por_sku")
    def test_garante_lucro_minimo_10(self, mock_listar_bling, _mock_alerta):
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
        out = repricing.executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        self.assertEqual(out["total_ajustes"], 1)
        ajuste = out["ajustes"][0]
        self.assertGreaterEqual(ajuste["margem_pct"], 10.0)
        self.assertGreaterEqual(ajuste["novo_preco"], 10.0)

    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos_por_sku")
    def test_nao_ajusta_sem_custo(self, mock_listar_bling, _mock_alerta):
        mock_listar_bling.return_value = {"SKU2": {"sku": "SKU2", "custo": 0.0}}
        produtos = [{"sku": "SKU2", "canais": {"shopee": {"ativo": True, "item_id": 1, "preco": 20.0}}}]
        out = repricing.executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        self.assertEqual(out["total_itens"], 0)
        self.assertEqual(out["total_ajustes"], 0)

    @patch("agentes.repricing.agente_repricing_marketplaces.buscar_menor_preco_concorrente")
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos_por_sku")
    def test_busca_concorrente_ao_vivo_quando_ausente(
        self, mock_listar_bling, _mock_alerta, mock_vivo
    ):
        """Sem preco_concorrente no payload (ML), deve buscar ao vivo."""
        mock_listar_bling.return_value = {"SKU3": {"sku": "SKU3", "custo": 9.5}}
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
        out = repricing.executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        mock_vivo.assert_called_once_with("MLB3")
        ajuste = out["ajustes"][0]
        self.assertEqual(ajuste["fonte_concorrente"], "ao_vivo")
        self.assertIn("economia_estimada_piso_margem", out)
        self.assertGreaterEqual(out["economia_estimada_piso_margem"], 0.0)

    @patch("agentes.repricing.agente_repricing_marketplaces.buscar_menor_preco_concorrente")
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos_por_sku")
    def test_nao_busca_ao_vivo_quando_payload_tem_preco(
        self, mock_listar_bling, _mock_alerta, mock_vivo
    ):
        """Com preco_concorrente no payload, NÃO chama a busca ao vivo."""
        mock_listar_bling.return_value = {"SKU4": {"sku": "SKU4", "custo": 9.5}}
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
        out = repricing.executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        mock_vivo.assert_not_called()
        self.assertEqual(out["ajustes"][0]["fonte_concorrente"], "payload")

    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos")
    def test_sem_produtos_chama_listar_produtos_apenas_uma_vez(self, mock_listar_produtos, _mock_alerta):
        mock_listar_produtos.return_value = [
            {"codigo": "SKU1", "sku": "SKU1", "custo": 9.5, "canais": {}},
        ]
        repricing.executar(dry_run=True, lucro_minimo_pct=10.0)
        mock_listar_produtos.assert_called_once()

    @patch.object(repricing, "_gerar_nota_concorrencia", return_value="concorrente sem frete grátis — considere manter preço")
    @patch.object(repricing, "_carregar_monitor_por_sku", return_value={"SKU-MON": {"termo_busca": "kit impala", "ativo": True, "sku": "SKU-MON"}})
    @patch("agentes.repricing.agente_repricing_marketplaces.buscar_menor_preco_concorrente")
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos_por_sku")
    def test_nota_concorrencia_quando_monitorado(
        self, mock_listar_bling, _mock_alerta, mock_vivo, _mock_monitor, mock_nota
    ):
        mock_listar_bling.return_value = {"SKU-MON": {"sku": "SKU-MON", "custo": 9.5}}
        mock_vivo.return_value = 30.0
        produtos = [
            {
                "sku": "SKU-MON",
                "nome": "Kit Monitor",
                "custo": 9.5,
                "canais": {
                    "mercadolivre": {"ativo": True, "item_id": "MLB-MON", "preco": 10.0}
                },
            }
        ]
        out = repricing.executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        ajuste = out["ajustes"][0]
        self.assertEqual(ajuste["fonte_concorrente"], "ao_vivo")
        self.assertIn("frete", ajuste["nota_concorrencia"].lower())
        mock_nota.assert_called_once()

    @patch.object(repricing, "_gerar_nota_concorrencia")
    @patch.object(repricing, "_carregar_monitor_por_sku", return_value={})
    @patch("agentes.repricing.agente_repricing_marketplaces.buscar_menor_preco_concorrente")
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos_por_sku")
    def test_sem_nota_sem_monitor(
        self, mock_listar_bling, _mock_alerta, mock_vivo, _mock_monitor, mock_nota
    ):
        mock_listar_bling.return_value = {"SKU3": {"sku": "SKU3", "custo": 9.5}}
        mock_vivo.return_value = 30.0
        produtos = [
            {
                "sku": "SKU3",
                "custo": 9.5,
                "canais": {"mercadolivre": {"ativo": True, "item_id": "MLB3", "preco": 10.0}},
            }
        ]
        out = repricing.executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        mock_nota.assert_not_called()
        self.assertIsNone(out["ajustes"][0].get("nota_concorrencia"))

    @patch.object(repricing, "_gerar_nota_concorrencia", return_value="nota informativa")
    @patch.object(repricing, "_carregar_monitor_por_sku", return_value={"SKU3": {"sku": "SKU3", "ativo": True}})
    @patch("agentes.repricing.agente_repricing_marketplaces.buscar_menor_preco_concorrente")
    @patch("agentes.repricing.agente_repricing_marketplaces.alertar_gestor")
    @patch("agentes.repricing.agente_repricing_marketplaces.listar_produtos_por_sku")
    def test_preco_identico_com_ou_sem_nota(
        self, mock_listar_bling, _mock_alerta, mock_vivo, _mock_monitor, _mock_nota
    ):
        mock_listar_bling.return_value = {"SKU3": {"sku": "SKU3", "custo": 9.5}}
        mock_vivo.return_value = 30.0
        produtos = [
            {
                "sku": "SKU3",
                "custo": 9.5,
                "canais": {"mercadolivre": {"ativo": True, "item_id": "MLB3", "preco": 10.0}},
            }
        ]
        with patch.object(repricing, "_gerar_nota_concorrencia", return_value=None):
            sem_nota = repricing.executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        com_nota = repricing.executar(produtos=produtos, dry_run=True, lucro_minimo_pct=10.0)
        self.assertEqual(
            sem_nota["ajustes"][0]["novo_preco"],
            com_nota["ajustes"][0]["novo_preco"],
        )


if __name__ == "__main__":
    unittest.main()
