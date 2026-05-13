"""
tests/test_agente_shopee.py — ASH01–ASH03
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.shopee import agente_shopee


class TestAgenteShopee(unittest.TestCase):
    @patch.object(agente_shopee, "time")
    @patch.object(agente_shopee, "responder_pergunta")
    @patch.object(
        agente_shopee,
        "listar_perguntas_nao_respondidas",
        return_value=[{"comment_id": 1, "comment": ""}],
    )
    def test_ASH01_ignora_texto_vazio(self, _mock_listar, mock_resp, _mock_time):
        agente_shopee.responder_perguntas()
        mock_resp.assert_not_called()

    @patch.object(agente_shopee, "time")
    @patch.object(agente_shopee, "responder_pergunta", return_value=True)
    @patch.object(agente_shopee, "responder_chat", return_value="Sim, temos frete grátis!")
    @patch.object(agente_shopee, "buscar_produto", return_value={"nome": "Kit", "preco": 59.9, "estoque": 50})
    @patch.object(
        agente_shopee,
        "listar_perguntas_nao_respondidas",
        return_value=[{"comment_id": 1, "item_id": "I1", "comment": "Tem frete?"}],
    )
    def test_ASH02_responde_com_claude(self, *_patches):
        agente_shopee.responder_perguntas()
        agente_shopee.responder_pergunta.assert_called_once()

    @patch("agentes.vendas_notificador.notificar_pedidos_novos_marketplace", return_value={})
    @patch.object(agente_shopee, "responder_perguntas", return_value=0)
    def test_ASH03_executar_retorna_dict(self, *_patches):
        out = agente_shopee.executar()
        self.assertIsInstance(out, dict)


if __name__ == "__main__":
    unittest.main()
