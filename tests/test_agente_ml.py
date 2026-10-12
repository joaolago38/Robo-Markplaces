"""
tests/test_agente_ml.py — AML01–AML09 + travas chat seguro
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.ml import agente_ml
from core.chat_seguro_ml import MSG_CONSULTAR_ANUNCIO, MSG_ESTOQUE_INCERTO, MSG_INDISPONIVEL


class TestAgenteMlValidacao(unittest.TestCase):
    def test_AML01_pergunta_valida_vazia(self):
        self.assertFalse(agente_ml.pergunta_valida(""))
        self.assertFalse(agente_ml.pergunta_valida(None))

    def test_AML02_pergunta_valida_com_conteudo(self):
        self.assertTrue(agente_ml.pergunta_valida("Tem frete grátis?"))

    def test_AML03_pergunta_valida_texto_curto(self):
        """Texto com menos de 3 caracteres é ignorado no fluxo (equivalente a rejeição curta)."""
        self.assertFalse(agente_ml.pergunta_valida("ok"))


class TestAgenteMlValidarResposta(unittest.TestCase):
    def test_sem_produto_confirma(self):
        out = agente_ml.validar_resposta("qualquer", {})
        self.assertIn("confirmar", out.lower())

    @patch.object(agente_ml, "buscar_produto", return_value={"sku": "S", "estoque": 0, "preco": 50})
    def test_estoque_zero_indisponivel(self, _):
        out = agente_ml.validar_resposta("Temos sim!", {"sku": "S", "estoque": 5, "preco": 50})
        self.assertEqual(out, MSG_INDISPONIVEL)

    @patch.object(agente_ml, "buscar_produto", return_value=None)
    def test_bling_ausente_fail_closed(self, _):
        out = agente_ml.validar_resposta("ok", {"sku": "S", "estoque": 5, "preco": 50})
        self.assertEqual(out, MSG_ESTOQUE_INCERTO)

    @patch.object(agente_ml, "buscar_produto", return_value={"sku": "S", "estoque": 3, "preco": 59.9})
    def test_frete_inventado_sanitizado(self, _):
        out = agente_ml.validar_resposta(
            "Chegará grátis amanhã com Full",
            {"sku": "S", "estoque": 3, "preco": 59.9},
        )
        self.assertEqual(out, MSG_CONSULTAR_ANUNCIO)

    def test_snapshot_sem_bling_ainda_sanitiza(self):
        from core.chat_seguro_ml import MSG_SEM_DESCONTO

        out = agente_ml.validar_resposta(
            "Temos desconto especial hoje",
            {"nome": "Kit", "preco": 44.9, "estoque": 0, "_fonte": "oferta_conversao_snapshot"},
        )
        self.assertEqual(out, MSG_SEM_DESCONTO)


class TestAgenteMlPreco(unittest.TestCase):
    @patch.object(agente_ml, "MARGEM_MINIMA", 0.10)
    def test_AML04_calcular_preco_respeita_margem_minima(self, *_patches):
        self.assertEqual(agente_ml.calcular_preco(100.0, 50.0, 95.0), 100.0)

    @patch.object(agente_ml, "MARGEM_MINIMA", 0.10)
    def test_AML04b_calcular_preco_abaixa_quando_margem_ok(self, *_patches):
        self.assertEqual(agente_ml.calcular_preco(100.0, 80.0, 50.0), 82.4)


class TestAgenteMlCiclo(unittest.TestCase):
    @patch.object(agente_ml, "time")
    @patch.object(agente_ml, "tentar_claim", return_value=True)
    @patch.object(agente_ml, "validar_resposta", side_effect=lambda r, p: r)
    @patch.object(agente_ml, "responder", return_value=True)
    @patch.object(agente_ml, "responder_chat", return_value="Resposta")
    @patch.object(
        agente_ml,
        "_montar_produto_resposta",
        return_value={"sku": "S", "estoque": 5, "preco": 50, "nome": "Kit"},
    )
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
    @patch.object(agente_ml, "tentar_claim", return_value=True)
    @patch.object(agente_ml, "validar_resposta", side_effect=lambda r, p: r)
    @patch.object(agente_ml, "responder", side_effect=[True, False, True])
    @patch.object(agente_ml, "responder_chat", return_value="Resposta")
    @patch.object(
        agente_ml,
        "_montar_produto_resposta",
        return_value={"sku": "S", "estoque": 5, "preco": 50, "nome": "Kit"},
    )
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

    @patch.object(agente_ml, "time")
    @patch.object(agente_ml, "tentar_claim", return_value=False)
    @patch.object(agente_ml, "responder")
    @patch.object(
        agente_ml,
        "buscar_perguntas",
        return_value=[{"id": "1", "text": "Pergunta um?", "item_id": "SKU-A"}],
    )
    def test_claim_bloqueia_resposta(self, _perguntas, mock_responder, *_):
        self.assertEqual(agente_ml.ciclo_chat(), 0)
        mock_responder.assert_not_called()



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
    @patch("integracoes.ml.alerta_pendencias_loja.emitir_alerta_p0_do_ciclo", return_value={"tem_p0": False})
    @patch("agentes.vendas_notificador.notificar_pedidos_novos_marketplace", return_value={})
    @patch.object(agente_ml, "verificar_reputacao", return_value={})
    @patch.object(agente_ml, "ciclo_chat", return_value=0)
    def test_AML09_executar_estrutura(self, *_patches):
        out = agente_ml.executar()
        self.assertIn("chat", out)
        self.assertIn("reputacao", out)
        self.assertIn("p0_loja", out)


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
