"""
tests/test_telegram_explicacao.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import notificador
from core import telegram_explicacao as te


class TestTelegramExplicacao(unittest.TestCase):
    def test_desligada_quando_flag_off_nao_injeta(self):
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
        self.assertIn("frequência", out.lower())
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
    def test_corpo_sem_cabecalho_remove_explicacao(self, _ativa):
        full = te.cabecalho_agente("leilao", "🏛️ *Leilão*")
        full = f"{full}\n\n*Corpo útil*\nItem A"
        corpo = te.corpo_sem_cabecalho(full)
        self.assertIn("Corpo útil", corpo)
        self.assertIn("Item A", corpo)
        self.assertNotIn("O que este agente faz", corpo)
        self.assertNotIn("Quando roda", corpo)
        self.assertNotIn("*Leilão*", corpo)

    @patch.object(te, "explicacao_ativa", return_value=True)
    def test_horario_novamix_diario(self, _ativa):
        out = te.inserir_explicacao("Título", "resumo_diario_novamix")
        self.assertIn("08:00 BRT", out)
        self.assertIn("fora do orquestrador", out)

    def test_chave_infere_agente(self):
        self.assertEqual(te.agente_id_da_chave("esmaltes:busca_kit:2026-07-12:resumo:x"), "monitor_busca_kit_esmaltes")
        self.assertEqual(te.agente_id_da_chave("sumare:leiloes:resumo:y"), "sumare_leiloes")

    def test_escapar_markdown_legado(self):
        self.assertEqual(te._escapar_markdown_legado("item_id e *preço*"), r"item\_id e \*preço\*")

    def test_sanitizar_preserva_negrito_e_escapa_interior(self):
        out = te.sanitizar_markdown_legado("*Kit Rosa_Pink*")
        self.assertEqual(out, r"*Kit Rosa\_Pink*")

    def test_sanitizar_underscore_solto(self):
        out = te.sanitizar_markdown_legado("SKU item_id ok")
        self.assertEqual(out, r"SKU item\_id ok")

    def test_sanitizar_url_com_underscore(self):
        out = te.sanitizar_markdown_legado("veja https://ml.com/item_abc_def e fim")
        self.assertIn(r"item\_abc\_def", out)
        self.assertTrue(out.startswith("veja https://"))

    def test_sanitizar_preserva_italico_e_link(self):
        out = te.sanitizar_markdown_legado("_oi_ e [nome_x](https://a.com/b_c)")
        self.assertIn("_oi_", out)
        self.assertIn(r"[nome\_x](", out)
        self.assertIn(r"b\_c", out)

    @patch.object(te, "explicacao_ativa", return_value=True)
    def test_explicacao_com_underscore_escapa(self, _ativa):
        with patch.dict(te.EXPLICACOES_AGENTES, {"leilao": "texto com item_id e mais"}):
            out = te.inserir_explicacao("Título", "leilao")
        self.assertIn(r"item\_id", out)
        # Não pode sobrar _ cru no corpo itálico (quebraria o Telegram)
        corpo = out.split("_O que este agente faz:_", 1)[-1]
        self.assertNotIn("item_id", corpo.replace(r"item\_id", ""))

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
