"""
tests/test_prontidao.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import prontidao


class ProntidaoTests(unittest.TestCase):
    @patch("core.prontidao.gestor_telegram_configurado", return_value=False)
    def test_bloqueia_sem_telegram(self, _mock):
        pode, motivo = prontidao.pode_alertar_esmaltes()
        self.assertFalse(pode)
        self.assertEqual(motivo, "telegram_nao_configurado")

    @patch.object(prontidao, "fonte_esmaltes_configurada", return_value=False)
    @patch("core.prontidao.gestor_telegram_configurado", return_value=True)
    def test_bloqueia_sem_fonte_dados(self, _mock_tg, _mock_fonte):
        pode, motivo = prontidao.pode_alertar_esmaltes()
        self.assertFalse(pode)
        self.assertIn("fonte_dados_nao_configurada", motivo)

    @patch.object(prontidao, "fonte_esmaltes_configurada", return_value=True)
    @patch("core.prontidao.gestor_telegram_configurado", return_value=True)
    def test_libera_quando_tudo_configurado(self, _mock_tg, _mock_fonte):
        pode, motivo = prontidao.pode_alertar_esmaltes()
        self.assertTrue(pode)
        self.assertEqual(motivo, "ok")

    @patch("core.prontidao.BRAVE_SEARCH_API_KEY", "chave-brave")
    def test_fonte_configurada_via_brave(self):
        with patch.object(prontidao, "ml_configurado", return_value=False):
            self.assertTrue(prontidao.fonte_esmaltes_configurada())

    @patch("core.prontidao.BRAVE_SEARCH_API_KEY", "")
    def test_fonte_nao_configurada(self):
        with patch.object(prontidao, "ml_configurado", return_value=False):
            self.assertFalse(prontidao.fonte_esmaltes_configurada())

    def test_ml_configurado_nunca_lanca(self):
        # Não deve lançar mesmo se ml_client falhar ao importar/checar.
        self.assertIn(prontidao.ml_configurado(), (True, False))

    @patch("core.prontidao.PROMOCOES_MANICURES_ATIVO", False)
    def test_promocoes_desativadas(self):
        pode, motivo = prontidao.pode_divulgar_promocoes_manicures()
        self.assertFalse(pode)
        self.assertEqual(motivo, "promocoes_desativadas")

    @patch("core.prontidao.PROMOCOES_MANICURES_ATIVO", True)
    @patch.object(prontidao, "whatsapp_grupo_manicures_pronto", return_value=False)
    @patch("core.prontidao.manicures_telegram_configurado", return_value=False)
    def test_promocoes_sem_canal(self, *_):
        pode, motivo = prontidao.pode_divulgar_promocoes_manicures()
        self.assertFalse(pode)
        self.assertIn("nenhum_canal", motivo)

    @patch("core.prontidao.PROMOCOES_MANICURES_ATIVO", True)
    @patch.object(prontidao, "whatsapp_grupo_manicures_pronto", return_value=False)
    @patch("core.prontidao.manicures_telegram_configurado", return_value=True)
    def test_promocoes_so_telegram(self, *_):
        pode, motivo = prontidao.pode_divulgar_promocoes_manicures()
        self.assertTrue(pode)


if __name__ == "__main__":
    unittest.main()
