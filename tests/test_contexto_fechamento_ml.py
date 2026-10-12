"""tests/test_contexto_fechamento_ml.py — snapshot Ads/oferta → chat ML (só leitura)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core import contexto_fechamento_ml as ctx
from integracoes.social.promocoes_manicures import link_ml_valido


class TestLinkMlValido(unittest.TestCase):
    def test_mlb_preencher_invalido(self):
        self.assertFalse(
            link_ml_valido("https://produto.mercadolivre.com.br/MLB_PREENCHER")
        )

    def test_mlb_real_ok(self):
        self.assertTrue(link_ml_valido("https://produto.mercadolivre.com.br/MLB1234567890"))


class TestContextoFechamento(unittest.TestCase):
    @patch.object(ctx, "ler_json")
    def test_sem_snapshot(self, mock_ler):
        mock_ler.return_value = {}
        out = ctx.carregar_contexto_fechamento_ml()
        self.assertTrue(out["ok"])  # dict vazio ainda é snapshot "lido"
        self.assertFalse(out["link_valido"])

    @patch.object(ctx, "ler_json")
    def test_com_oferta_e_ads(self, mock_ler):
        mock_ler.return_value = {
            "timestamp": "2026-07-10T12:00:00Z",
            "ads": {
                "gasto": 50,
                "sustentabilidade": {"status": "alerta", "roas_real": 1.2},
            },
            "oferta": {
                "campanha_id": "kit-3",
                "campanha_nome": "Kit 3",
                "sku": "SKU1",
                "link_ml": "https://produto.mercadolivre.com.br/MLB999",
                "preco_brl": 44.9,
            },
        }
        out = ctx.carregar_contexto_fechamento_ml()
        self.assertTrue(out["ok"])
        self.assertTrue(out["link_valido"])
        self.assertEqual(out["link_ml"], "https://produto.mercadolivre.com.br/MLB999")
        self.assertEqual(out["sinal_ads"]["oferta_ativa_id"], "kit-3")
        self.assertEqual(out["oferta"]["sku"], "SKU1")

    @patch.object(ctx, "ler_json")
    def test_link_placeholder_invalido(self, mock_ler):
        mock_ler.return_value = {
            "oferta": {"link_ml": "https://x/MLB_PREENCHER", "campanha_id": "k"},
            "ads": {},
        }
        out = ctx.carregar_contexto_fechamento_ml()
        self.assertFalse(out["link_valido"])


class TestBloqueioBoostLink(unittest.TestCase):
    def test_bloqueia_link_invalido(self):
        from agentes.social import agente_conversao_manicures as ag

        with patch.object(ag, "CONVERSAO_BLOQUEAR_LINK_INVALIDO", True):
            ok, motivo = ag._pode_impulsionar_ativo(
                {}, oferta={"link_valido": False}
            )
        self.assertFalse(ok)
        self.assertEqual(motivo, "bloqueado_link_ml_invalido")

    def test_permite_link_ok(self):
        from agentes.social import agente_conversao_manicures as ag

        with patch.object(ag, "CONVERSAO_BLOQUEAR_LINK_INVALIDO", True), patch.object(
            ag, "CONVERSAO_MANICURES_SUSTENTABILIDADE", False
        ):
            ok, motivo = ag._pode_impulsionar_ativo(
                {}, oferta={"link_valido": True}
            )
        self.assertTrue(ok)
        self.assertEqual(motivo, "")


if __name__ == "__main__":
    unittest.main()
