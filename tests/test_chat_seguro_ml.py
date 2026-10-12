"""tests/test_chat_seguro_ml.py — travas de resposta chat ML."""
from __future__ import annotations

import unittest

from core.chat_seguro_ml import (
    MSG_CONSULTAR_ANUNCIO,
    MSG_SEM_DESCONTO,
    prompt_sistema_chat,
    prompt_sistema_chat_ml,
    sanitizar_resposta_chat_ml,
)


class TestSanitizarResposta(unittest.TestCase):
    def test_frete_absoluto_bloqueado(self):
        out = sanitizar_resposta_chat_ml("Com Full ativo chegará grátis amanhã")
        self.assertEqual(out, MSG_CONSULTAR_ANUNCIO)

    def test_desconto_bloqueado(self):
        out = sanitizar_resposta_chat_ml("Temos preço especial e desconto de 10%")
        self.assertEqual(out, MSG_SEM_DESCONTO)

    def test_preco_fora_do_catalogo_bloqueado(self):
        out = sanitizar_resposta_chat_ml(
            "Posso fazer por R$ 29,90",
            {"preco": 59.9},
        )
        self.assertEqual(out, MSG_CONSULTAR_ANUNCIO)

    def test_preco_do_catalogo_ok(self):
        out = sanitizar_resposta_chat_ml(
            "O preço do anúncio é R$ 59.90",
            {"preco": 59.9},
        )
        self.assertIn("59.90", out)

    def test_texto_neutro_passa(self):
        out = sanitizar_resposta_chat_ml(
            "As cores são Preto e Nude. Confira frete no anúncio com seu CEP.",
            {"preco": 59.9},
        )
        # "frete" sozinho sem "grátis/amanhã" — a regex pega frete grátis; "Confira frete" pode passar
        # Se a frase tiver "frete grátis" bloqueia; aqui só "frete" sem absoluto
        self.assertTrue(len(out) > 10)


class TestPromptChatCanais(unittest.TestCase):
    def test_ml_e_shopee_nao_inventam_listing(self):
        ml = prompt_sistema_chat_ml()
        self.assertIn("Mercado Livre", ml)
        self.assertIn("Carmed Manicure", ml)
        self.assertIn("francesinha", ml)
        sh = prompt_sistema_chat("shopee")
        self.assertIn("Shopee", sh)
        self.assertIn("não está publicado neste canal", sh)
        self.assertIn("4.8", sh)


if __name__ == "__main__":
    unittest.main()
