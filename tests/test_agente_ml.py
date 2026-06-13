"""
tests/test_agente_ml.py — AML01–AML09
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.ml import agente_ml


class TestAgenteMlValidacao(unittest.TestCase):
    def test_AML01_pergunta_valida_vazia(self):
        self.assertFalse(agente_ml.pergunta_valida(""))
        self.assertFalse(agente_ml.pergunta_valida(None))

    def test_AML02_pergunta_valida_com_conteudo(self):
        self.assertTrue(agente_ml.pergunta_valida("Tem frete grátis?"))

    def test_AML03_pergunta_valida_texto_curto(self):
        """Texto com menos de 3 caracteres é ignorado no fluxo (equivalente a rejeição curta)."""
        self.assertFalse(agente_ml.pergunta_valida("ok"))


class TestAgenteMlPreco(unittest.TestCase):
    @patch.object(agente_ml, "MARGEM_MINIMA", 0.10)
    def test_AML04_calcular_preco_respeita_margem_minima(self, *_patches):
        self.assertEqual(agente_ml.calcular_preco(100.0, 50.0, 95.0), 100.0)

    @patch.object(agente_ml, "MARGEM_MINIMA", 0.10)
    def test_AML04b_calcular_preco_abaixa_quando_margem_ok(self, *_patches):
        self.assertEqual(agente_ml.calcular_preco(100.0, 80.0, 50.0), 82.4)


class TestAgenteMlCiclo(unittest.TestCase):
    @patch.object(agente_ml, "time")
    @patch.object(agente_ml, "responder", return_value=True)
    @patch.object(agente_ml, "responder_chat", return_value="Resposta")
    @patch.object(agente_ml, "buscar_produto", return_value={"sku": "S", "estoque": 5})
    @patch.object(
        agente_ml,
        "buscar_perguntas",
        return_value=[
            {"id": "1", "text": "Pergunta um?", "item_id": "SKU-A"},
            {"id": "2", "text": "Pergunta dois?", "item_id": "SKU-B"},
            {"id": "3", "text": "Pergunta três?", "item_id": "SKU-C"},
        ],
    )
    def test_AML05_ciclo_chat_responde_todas(self, *_patches):
        self.assertEqual(agente_ml.ciclo_chat(), 3)

    @patch.object(agente_ml, "time")
    @patch.object(agente_ml, "responder", side_effect=[True, False, True])
    @patch.object(agente_ml, "responder_chat", return_value="Resposta")
    @patch.object(agente_ml, "buscar_produto", return_value={"sku": "S", "estoque": 5})
    @patch.object(
        agente_ml,
        "buscar_perguntas",
        return_value=[
            {"id": "1", "text": "Pergunta um?", "item_id": "SKU-A"},
            {"id": "2", "text": "Pergunta dois?", "item_id": "SKU-B"},
            {"id": "3", "text": "Pergunta três?", "item_id": "SKU-C"},
        ],
    )
    def test_AML06_ciclo_chat_conta_sucesso(self, *_patches):
        self.assertEqual(agente_ml.ciclo_chat(), 2)


class TestAgenteMlReputacao(unittest.TestCase):
    @patch.object(agente_ml, "buscar_reputacao_vendedor")
    def test_AML07_verificar_reputacao_retorna_dados(self, mock_rep):
        mock_rep.return_value = {
            "level_id": "5_green",
            "metrics": {"claims": {"rate": 0.0}},
        }
        out = agente_ml.verificar_reputacao()
        self.assertIn("level_id", out)

    @patch.object(agente_ml, "alertar_critico")
    @patch.object(agente_ml, "buscar_reputacao_vendedor")
    def test_AML08_verificar_reputacao_alerta_claims(self, mock_rep, mock_crit):
        mock_rep.return_value = {"metrics": {"claims": {"rate": 0.02}}}
        agente_ml.verificar_reputacao()
        mock_crit.assert_called_once()


class TestAgenteMlExecutar(unittest.TestCase):
    @patch("agentes.vendas_notificador.notificar_pedidos_novos_marketplace", return_value={})
    @patch.object(agente_ml, "verificar_reputacao", return_value={})
    @patch.object(agente_ml, "ciclo_chat", return_value=0)
    def test_AML09_executar_estrutura(self, *_patches):
        out = agente_ml.executar()
        self.assertIn("chat", out)
        self.assertIn("reputacao", out)


class TestAgenteMlAnuncios(unittest.TestCase):
    @patch.object(agente_ml, "pausar_anuncio", return_value={"ok": True, "dry_run": True})
    def test_AML10_gerenciar_pausar(self, mock_pausar):
        out = agente_ml.gerenciar_status_anuncio("MLB1", "pausar", dry_run=True)
        self.assertTrue(out["ok"])
        mock_pausar.assert_called_once_with("MLB1", dry_run=True, confirmar=False)

    def test_AML11_acao_invalida(self):
        out = agente_ml.gerenciar_status_anuncio("MLB1", "explodir")
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
