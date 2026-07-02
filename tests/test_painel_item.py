"""tests/test_painel_item.py"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.painel_item import montar_painel_item

ITEM_ID = "MLB123456"
SKU = "KIT-001"


class TestMontarPainelItem(unittest.TestCase):
  @patch("agentes.painel_item.buscar_produto")
  @patch("agentes.painel_item.ml_client.listar_meus_anuncios")
  @patch("agentes.painel_item.ml_client.listar_pedidos_detalhado")
  @patch("agentes.painel_item.ml_client.buscar_metricas_item")
  def test_caminho_feliz(
      self, mock_metricas, mock_pedidos, mock_anuncios, mock_bling
  ):
    mock_metricas.return_value = {
      "titulo": "Kit Impala",
      "status": "active",
      "preco": 50.0,
      "estoque": 12,
      "visitas_7d": 100,
      "visitas_30d": 400,
    }
    mock_pedidos.return_value = (
      [
        {
          "order_id": "O1",
          "itens": [
            {"item_id": ITEM_ID, "quantidade": 2, "preco_unitario": 50.0},
            {"item_id": "MLB999", "quantidade": 5, "preco_unitario": 10.0},
          ],
        },
        {
          "order_id": "O2",
          "itens": [
            {"item_id": ITEM_ID, "quantidade": 1, "preco_unitario": 48.0},
          ],
        },
      ],
      True,
    )
    mock_anuncios.return_value = [{"item_id": ITEM_ID, "sku": SKU}]
    mock_bling.return_value = {"custo": 20.0}

    out = montar_painel_item(ITEM_ID, dias=7)

    self.assertEqual(out["unidades_vendidas"], 3)
    self.assertEqual(out["vendas_por_dia"], round(3 / 7, 2))
    self.assertEqual(out["receita_bruta_total"], 148.0)  # 2*50 + 1*48
    self.assertEqual(out["receita_liquida_unitaria"], 30.0)  # 50 - 20
    self.assertEqual(out["receita_liquida_total"], 88.0)  # 148 - 3*20
    self.assertTrue(out["metricas_ok"])
    self.assertTrue(out["pedidos_ok"])
    self.assertTrue(out["custo_ok"])

  @patch("agentes.painel_item.buscar_produto")
  @patch("agentes.painel_item.ml_client.listar_meus_anuncios")
  @patch("agentes.painel_item.ml_client.listar_pedidos_detalhado")
  @patch("agentes.painel_item.ml_client.buscar_metricas_item")
  def test_item_id_vazio_nao_chama_apis(
      self, mock_metricas, mock_pedidos, mock_anuncios, mock_bling
  ):
    out = montar_painel_item("")
    self.assertEqual(out["erro"], "item_id vazio")
    mock_metricas.assert_not_called()
    mock_pedidos.assert_not_called()
    mock_anuncios.assert_not_called()
    mock_bling.assert_not_called()

  @patch("agentes.painel_item.buscar_produto")
  @patch("agentes.painel_item.ml_client.listar_meus_anuncios")
  @patch("agentes.painel_item.ml_client.listar_pedidos_detalhado")
  @patch("agentes.painel_item.ml_client.buscar_metricas_item")
  def test_pedidos_falha_api(
      self, mock_metricas, mock_pedidos, mock_anuncios, mock_bling
  ):
    mock_metricas.return_value = {"preco": 10.0, "titulo": "X", "status": "active"}
    mock_pedidos.return_value = ([], False)
    mock_anuncios.return_value = []
    mock_bling.return_value = None

    out = montar_painel_item(ITEM_ID, dias=7)
    self.assertFalse(out["pedidos_ok"])
    self.assertEqual(out["unidades_vendidas"], 0)
    self.assertEqual(out["receita_bruta_total"], 0.0)

  @patch("agentes.painel_item.buscar_produto")
  @patch("agentes.painel_item.ml_client.listar_meus_anuncios")
  @patch("agentes.painel_item.ml_client.listar_pedidos_detalhado")
  @patch("agentes.painel_item.ml_client.buscar_metricas_item")
  def test_sem_sku_no_ml(
      self, mock_metricas, mock_pedidos, mock_anuncios, mock_bling
  ):
    mock_metricas.return_value = {"preco": 40.0, "titulo": "Y", "status": "active"}
    mock_pedidos.return_value = ([], True)
    mock_anuncios.return_value = [{"item_id": "MLB-OUTRO", "sku": "OUTRO"}]

    out = montar_painel_item(ITEM_ID, dias=7)
    self.assertIsNone(out["sku"])
    self.assertFalse(out["custo_ok"])
    self.assertIsNone(out["receita_liquida_unitaria"])
    self.assertIsNone(out["receita_liquida_total"])
    mock_bling.assert_not_called()

  @patch("agentes.painel_item.buscar_produto")
  @patch("agentes.painel_item.ml_client.listar_meus_anuncios")
  @patch("agentes.painel_item.ml_client.listar_pedidos_detalhado")
  @patch("agentes.painel_item.ml_client.buscar_metricas_item")
  def test_sku_sem_produto_bling(
      self, mock_metricas, mock_pedidos, mock_anuncios, mock_bling
  ):
    mock_metricas.return_value = {"preco": 40.0, "titulo": "Y", "status": "active"}
    mock_pedidos.return_value = ([], True)
    mock_anuncios.return_value = [{"item_id": ITEM_ID, "sku": SKU}]
    mock_bling.return_value = None

    out = montar_painel_item(ITEM_ID, dias=7)
    self.assertEqual(out["sku"], SKU)
    self.assertFalse(out["custo_ok"])
    self.assertIsNone(out["receita_liquida_unitaria"])
    self.assertIsNone(out["receita_liquida_total"])

  @patch("agentes.painel_item.buscar_produto")
  @patch("agentes.painel_item.ml_client.listar_meus_anuncios")
  @patch("agentes.painel_item.ml_client.listar_pedidos_detalhado")
  @patch("agentes.painel_item.ml_client.buscar_metricas_item")
  def test_soma_apenas_item_pedido(
      self, mock_metricas, mock_pedidos, mock_anuncios, mock_bling
  ):
    mock_metricas.return_value = {"preco": 30.0, "titulo": "Z", "status": "active"}
    mock_pedidos.return_value = (
      [
        {
          "itens": [
            {"item_id": ITEM_ID, "quantidade": 4, "preco_unitario": 30.0},
            {"item_id": "MLB-OUTRO", "quantidade": 10, "preco_unitario": 5.0},
          ]
        }
      ],
      True,
    )
    mock_anuncios.return_value = [{"item_id": ITEM_ID, "sku": SKU}]
    mock_bling.return_value = {"custo": 10.0}

    out = montar_painel_item(ITEM_ID, dias=7)
    self.assertEqual(out["unidades_vendidas"], 4)
    self.assertEqual(out["receita_bruta_total"], 120.0)


if __name__ == "__main__":
  unittest.main()
