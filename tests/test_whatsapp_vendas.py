"""
tests/test_whatsapp_vendas.py
Testa notificações de vendas via WhatsApp.
"""
import unittest
from unittest.mock import patch

from agentes.vendas_notificador import _notificar_novos_pedidos, executar


PEDIDOS_MOCK_ML = [
    {
        "order_id": "1001",
        "status": "paid",
        "total": 49.90,
        "data": "2025-05-01T10:00:00",
        "itens": [
            {
                "sku": "IMP-MIMO-003",
                "quantidade": 1,
                "preco_unitario": 49.90,
                "item_id": "MLB123",
            }
        ],
    },
    {
        "order_id": "1002",
        "status": "paid",
        "total": 89.90,
        "data": "2025-05-01T11:00:00",
        "itens": [
            {
                "sku": "IMP-SORT-006",
                "quantidade": 1,
                "preco_unitario": 89.90,
                "item_id": "MLB456",
            }
        ],
    },
]


class TestWhatsAppVendas(unittest.TestCase):

    @patch("agentes.vendas_notificador.notificar_venda", return_value=True)
    def test_notifica_pedidos_novos(self, mock_wpp):
        """Deve notificar todos os pedidos não vistos antes."""
        novos = _notificar_novos_pedidos("mercadolivre", PEDIDOS_MOCK_ML, set())
        self.assertEqual(len(novos), 2)
        self.assertEqual(mock_wpp.call_count, 2)

    @patch("agentes.vendas_notificador.notificar_venda", return_value=True)
    def test_nao_duplica_pedidos_ja_notificados(self, mock_wpp):
        """Não deve notificar pedidos já presentes no conjunto de notificados."""
        ja_notificados = {"mercadolivre:1001", "mercadolivre:1002"}
        novos = _notificar_novos_pedidos("mercadolivre", PEDIDOS_MOCK_ML, ja_notificados)
        self.assertEqual(len(novos), 0)
        mock_wpp.assert_not_called()

    @patch("agentes.vendas_notificador.notificar_venda", return_value=True)
    def test_notifica_apenas_pedido_novo(self, mock_wpp):
        """Só deve notificar o pedido que ainda não foi notificado."""
        ja_notificados = {"mercadolivre:1001"}
        novos = _notificar_novos_pedidos("mercadolivre", PEDIDOS_MOCK_ML, ja_notificados)
        self.assertEqual(len(novos), 1)
        self.assertIn("mercadolivre:1002", novos)
        mock_wpp.assert_called_once()

    @patch("agentes.vendas_notificador.notificar_venda", return_value=False)
    def test_falha_whatsapp_nao_marca_como_notificado(self, mock_wpp):
        """Se WhatsApp falhar, não deve marcar pedido como notificado."""
        novos = _notificar_novos_pedidos("mercadolivre", PEDIDOS_MOCK_ML, set())
        self.assertEqual(len(novos), 0)

    @patch("integracoes.amazon.amazon_client.listar_pedidos", return_value=[])
    @patch("integracoes.magalu.magalu_client.listar_pedidos", return_value=[])
    @patch("integracoes.shopee.shopee_client.listar_pedidos", return_value=[])
    @patch("agentes.vendas_notificador._salvar_notificados")
    @patch("agentes.vendas_notificador._carregar_notificados", return_value=set())
    @patch("agentes.vendas_notificador.notificar_venda", return_value=True)
    @patch("integracoes.ml.ml_client.listar_pedidos", return_value=PEDIDOS_MOCK_ML)
    def test_executar_retorna_resumo(
        self,
        mock_ml,
        mock_wpp,
        mock_carregar,
        mock_salvar,
        mock_sh,
        mock_mag,
        mock_amz,
    ):
        """executar() deve retornar dict com total e por marketplace."""
        resultado = executar()
        self.assertIn("total_notificacoes", resultado)
        self.assertIn("por_marketplace", resultado)
        self.assertEqual(resultado["por_marketplace"].get("mercadolivre", 0), 2)


if __name__ == "__main__":
    unittest.main()
