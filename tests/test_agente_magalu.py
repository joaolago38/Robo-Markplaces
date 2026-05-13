"""
tests/test_agente_magalu.py — AMG01–AMG06
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.magalu import agente_magalu


class TestAgenteMagaluValidar(unittest.TestCase):
    def test_AMG01_validar_produto_none(self):
        self.assertFalse(agente_magalu.validar_produto(None))

    def test_AMG02_validar_produto_sem_estoque(self):
        self.assertFalse(agente_magalu.validar_produto({"preco": 10.0}))

    def test_AMG03_validar_produto_completo(self):
        self.assertTrue(agente_magalu.validar_produto({"nome": "Kit", "preco": 59.9, "estoque": 50}))


class TestAgenteMagaluFluxo(unittest.TestCase):
    @patch.object(agente_magalu, "time")
    @patch.object(agente_magalu, "responder_pergunta", return_value=True)
    @patch.object(agente_magalu, "responder_chat", return_value="ok")
    @patch.object(agente_magalu, "buscar_produto", return_value={"nome": "K", "estoque": 10})
    @patch.object(
        agente_magalu,
        "listar_perguntas_nao_respondidas",
        return_value=[
            {"id": "q1", "sku": "S1", "question": "Um?"},
            {"id": "q2", "sku": "S2", "question": "Dois?"},
        ],
    )
    def test_AMG04_processar_perguntas_duas_vezes(self, *_patches):
        agente_magalu.processar_perguntas()
        self.assertEqual(agente_magalu.responder_pergunta.call_count, 2)

    @patch.object(agente_magalu, "monitorar_metricas", return_value={"devolucao": 0.01})
    @patch.object(agente_magalu, "processar_perguntas", return_value=0)
    def test_AMG06_executar_dict(self, *_patches):
        out = agente_magalu.executar()
        self.assertIsInstance(out, dict)


class TestAgenteMagaluMetricas(unittest.TestCase):
    def test_AMG05_monitorar_metricas_estrutura(self):
        out = agente_magalu.monitorar_metricas()
        self.assertTrue("devolucao" in out or "status" in out)


if __name__ == "__main__":
    unittest.main()
