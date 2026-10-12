"""
tests/test_agente_amazon.py — AAM01–AAM03
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.amazon import agente_amazon


class TestAgenteAmazon(unittest.TestCase):
    @patch.object(agente_amazon, "time")
    @patch.object(agente_amazon, "responder_mensagem", return_value=True)
    @patch.object(agente_amazon, "responder_chat", return_value="Prazo é 5 dias.")
    @patch.object(agente_amazon, "buscar_produto", return_value={"nome": "Kit", "estoque": 10})
    @patch.object(
        agente_amazon,
        "listar_mensagens_nao_respondidas",
        return_value=[{"id": "m1", "text": "Prazo?"}],
    )
    def test_AAM01_processar_chama_responder(self, *_patches):
        agente_amazon.processar_mensagens()
        agente_amazon.responder_mensagem.assert_called_once()

    @patch.object(agente_amazon, "listar_mensagens_nao_respondidas", return_value=[])
    def test_AAM02_processar_lista_vazia(self, *_patches):
        self.assertEqual(agente_amazon.processar_mensagens(), 0)

    @patch.object(agente_amazon, "skip_se_spec_inativo", return_value=None)
    @patch("agentes.vendas_notificador.notificar_pedidos_novos_marketplace", return_value={})
    @patch.object(agente_amazon, "processar_mensagens", return_value=0)
    def test_AAM03_executar_dict(self, *_patches):
        out = agente_amazon.executar()
        self.assertIsInstance(out, dict)
        self.assertIn("respostas", out)


if __name__ == "__main__":
    unittest.main()
