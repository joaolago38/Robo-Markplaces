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
    def test_inserir_apos_titulo(self):
        msg = "🔍 *Busca kit esmaltes — frequência diária*\nData: 2026-07-12"
        out = te.inserir_explicacao(msg, "monitor_busca_kit_esmaltes")
        self.assertIn("O que este agente faz", out)
        self.assertIn("Anita e Impala", out)
        self.assertIn("Data: 2026-07-12", out)
        # título continua na primeira linha
        self.assertTrue(out.startswith("🔍 *Busca kit"))

    def test_nao_duplica(self):
        msg = te.inserir_explicacao("Título\ncorpo", "leilao")
        out2 = te.inserir_explicacao(msg, "leilao")
        self.assertEqual(msg.count("O que este agente faz"), 1)
        self.assertEqual(out2, msg)

    def test_chave_infere_agente(self):
        self.assertEqual(te.agente_id_da_chave("esmaltes:busca_kit:2026-07-12:resumo:x"), "monitor_busca_kit_esmaltes")
        self.assertEqual(te.agente_id_da_chave("sumare:leiloes:resumo:y"), "sumare_leiloes")

    @patch.object(notificador, "_enviar", return_value=True)
    @patch.object(notificador, "_deve_suprimir", return_value=False)
    @patch.object(notificador, "_marcar_enviado")
    def test_alertar_gestor_injeta_via_chave(self, _marcar, _sup, mock_enviar):
        notificador.alertar_gestor(
            "🔍 *Busca kit*\nLinha2",
            chave="esmaltes:busca_kit:hoje",
            _ignorar_cooldown=True,
        )
        enviado = mock_enviar.call_args[0][1]
        self.assertIn("O que este agente faz", enviado)
        self.assertIn("frequência", enviado.lower())


if __name__ == "__main__":
    unittest.main()
