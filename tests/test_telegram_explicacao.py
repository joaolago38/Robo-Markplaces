"""
tests/test_telegram_explicacao.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import telegram_explicacao as te
from core import notificador


class TestTelegramExplicacao(unittest.TestCase):
    def test_desligada_por_padrao_nao_injeta(self):
        msg = "🔍 *Busca kit*\nData: 2026-07-12"
        with patch.object(te, "explicacao_ativa", return_value=False):
            out = te.inserir_explicacao(msg, "monitor_busca_kit_esmaltes")
        self.assertEqual(out, msg)
        self.assertNotIn("O que este agente faz", out)

    @patch.object(te, "explicacao_ativa", return_value=True)
    def test_inserir_apos_titulo(self, _ativa):
        msg = "🔍 *Busca kit esmaltes — frequência diária*\nData: 2026-07-12"
        out = te.inserir_explicacao(msg, "monitor_busca_kit_esmaltes")
        self.assertIn("O que este agente faz", out)
        self.assertIn("Anita e Impala", out)
        self.assertIn("Quando roda", out)
        self.assertIn("A cada 4h", out)
        self.assertIn("Data: 2026-07-12", out)
        self.assertTrue(out.startswith("🔍 *Busca kit"))

    @patch.object(te, "explicacao_ativa", return_value=True)
    def test_nao_duplica(self, _ativa):
        msg = te.inserir_explicacao("Título\ncorpo", "leilao")
        out2 = te.inserir_explicacao(msg, "leilao")
        self.assertEqual(msg.count("O que este agente faz"), 1)
        self.assertEqual(msg.count("Quando roda"), 1)
        self.assertEqual(out2, msg)

    @patch.object(te, "explicacao_ativa", return_value=True)
    def test_horario_novamix_diario(self, _ativa):
        out = te.inserir_explicacao("Título", "resumo_diario_novamix")
        self.assertIn("08:00 BRT", out)
        self.assertIn("fora do orquestrador", out)

    def test_chave_infere_agente(self):
        self.assertEqual(te.agente_id_da_chave("esmaltes:busca_kit:2026-07-12:resumo:x"), "monitor_busca_kit_esmaltes")
        self.assertEqual(te.agente_id_da_chave("sumare:leiloes:resumo:y"), "sumare_leiloes")

    @patch.object(te, "explicacao_ativa", return_value=False)
    @patch.object(notificador, "_enviar", return_value=True)
    @patch.object(notificador, "_deve_suprimir", return_value=False)
    @patch.object(notificador, "_marcar_enviado")
    def test_alertar_gestor_sem_explicacao_quando_off(self, _marcar, _sup, mock_enviar, _ativa):
        notificador.alertar_gestor(
            "🔍 *Busca kit*\nLinha2",
            chave="esmaltes:busca_kit:hoje",
            _ignorar_cooldown=True,
        )
        enviado = mock_enviar.call_args[0][1]
        self.assertNotIn("O que este agente faz", enviado)
        self.assertIn("Busca kit", enviado)

    @patch.object(te, "explicacao_ativa", return_value=True)
    @patch.object(notificador, "_enviar", return_value=True)
    @patch.object(notificador, "_deve_suprimir", return_value=False)
    @patch.object(notificador, "_marcar_enviado")
    def test_alertar_gestor_injeta_quando_on(self, _marcar, _sup, mock_enviar, _ativa):
        notificador.alertar_gestor(
            "🔍 *Busca kit*\nLinha2",
            chave="esmaltes:busca_kit:hoje",
            _ignorar_cooldown=True,
        )
        enviado = mock_enviar.call_args[0][1]
        self.assertIn("O que este agente faz", enviado)
        self.assertIn("Quando roda", enviado)
        self.assertIn("frequência", enviado.lower())


if __name__ == "__main__":
    unittest.main()
