"""
tests/test_blindspots_shopee_amazon.py
Cobertura das correções de confiança de dados real-time em Shopee e Amazon.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.amazon import amazon_client as amz
from integracoes.shopee import shopee_client as shopee


def _resp(status: int, body: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = str(body or "")
    r.json.return_value = body or {}
    r.raise_for_status = MagicMock()
    return r


class TestShopeeRegistrarAcessoSoEmSucesso(unittest.TestCase):
    @patch.object(shopee, "registrar_acesso")
    @patch.object(shopee, "_listar_perguntas_nao_respondidas_detalhado", return_value=([], False))
    @patch.object(shopee, "_enabled", return_value=True)
    def test_nao_registra_acesso_quando_busca_falha(self, *_patches):
        shopee.obter_saude_conta()
        shopee.registrar_acesso.assert_not_called()

    @patch.object(shopee, "registrar_acesso")
    @patch.object(shopee, "_listar_perguntas_nao_respondidas_detalhado", return_value=([{"id": 1}], True))
    @patch.object(shopee, "_enabled", return_value=True)
    def test_registra_acesso_quando_busca_funciona(self, *_patches):
        shopee.obter_saude_conta()
        shopee.registrar_acesso.assert_called_once_with("shopee")


class TestAmazonRegistrarAcessoSoEmSucesso(unittest.TestCase):
    @patch.object(amz, "registrar_acesso")
    @patch.object(amz, "listar_mensagens_nao_respondidas_detalhado", return_value=([], False))
    @patch.object(amz, "_enabled", return_value=True)
    def test_nao_registra_acesso_quando_busca_falha(self, *_patches):
        amz.obter_saude_conta()
        amz.registrar_acesso.assert_not_called()

    @patch.object(amz, "registrar_acesso")
    @patch.object(amz, "listar_mensagens_nao_respondidas_detalhado", return_value=([{"id": 1}], True))
    @patch.object(amz, "_enabled", return_value=True)
    def test_registra_acesso_quando_busca_funciona(self, *_patches):
        amz.obter_saude_conta()
        amz.registrar_acesso.assert_called_once_with("amazon")


class TestShopeeListarPedidosDetalhado(unittest.TestCase):
    @patch.object(shopee, "_params", return_value={})
    @patch.object(shopee, "request")
    @patch.object(shopee, "_enabled", return_value=True)
    def test_status_diferente_de_200_retorna_ok_false(self, _en, mock_request, _params):
        mock_request.return_value = _resp(401, {})
        pedidos, ok = shopee.listar_pedidos_detalhado(dias=1)
        self.assertFalse(ok)
        self.assertEqual(pedidos, [])

    @patch.object(shopee, "_params", return_value={})
    @patch.object(shopee, "request")
    @patch.object(shopee, "_enabled", return_value=True)
    def test_lista_vazia_com_api_ok_retorna_ok_true(self, _en, mock_request, _params):
        mock_request.return_value = _resp(200, {"response": {"order_list": [], "more": False}})
        pedidos, ok = shopee.listar_pedidos_detalhado(dias=1)
        self.assertTrue(ok)
        self.assertEqual(pedidos, [])

    @patch.object(shopee, "_enabled", return_value=False)
    def test_nao_configurado_retorna_ok_false(self, _en):
        pedidos, ok = shopee.listar_pedidos_detalhado(dias=1)
        self.assertFalse(ok)
        self.assertEqual(pedidos, [])


class TestAmazonListarPedidosDetalhado(unittest.TestCase):
    @patch.object(amz, "request")
    @patch.object(amz, "_enabled", return_value=True)
    def test_status_diferente_de_200_retorna_ok_false(self, _en, mock_request):
        mock_request.return_value = _resp(401, {})
        pedidos, ok = amz.listar_pedidos_detalhado(dias=1)
        self.assertFalse(ok)
        self.assertEqual(pedidos, [])

    @patch.object(amz, "request")
    @patch.object(amz, "_enabled", return_value=True)
    def test_lista_vazia_com_api_ok_retorna_ok_true(self, _en, mock_request):
        mock_request.return_value = _resp(200, {"payload": {"Orders": []}})
        pedidos, ok = amz.listar_pedidos_detalhado(dias=1)
        self.assertTrue(ok)
        self.assertEqual(pedidos, [])

    @patch.object(amz, "_enabled", return_value=False)
    def test_nao_configurado_retorna_ok_false(self, _en):
        pedidos, ok = amz.listar_pedidos_detalhado(dias=1)
        self.assertFalse(ok)
        self.assertEqual(pedidos, [])


if __name__ == "__main__":
    unittest.main()
