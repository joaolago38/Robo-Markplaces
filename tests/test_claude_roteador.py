"""tests/test_claude_roteador.py — ponto de mudança Haiku → Sonnet vendas ML."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core import claude_roteador as r


class TestClaudeRoteador(unittest.TestCase):
    def test_oferta_so_calor_fica_haiku_sem_pressao(self):
        """Padrão novo: oferta sem Ads alerta e sem análise alta → Haiku."""
        with patch.object(r, "restante_orcamento_usd", return_value=5.0), patch.object(
            r, "_cfg"
        ) as cfg:
            cfg.return_value.CLAUDE_ESCALONAR_ML = True
            cfg.return_value.CLAUDE_ESCALONAR_OFERTA = True
            cfg.return_value.CLAUDE_ESCALONAR_OFERTA_SO_CALOR = True
            cfg.return_value.CLAUDE_ESCALONAR_RESTANTE_MIN_USD = 1.5
            cfg.return_value.CLAUDE_MODELO_RAPIDO = "claude-haiku-4-5"
            cfg.return_value.CLAUDE_MODELO_VENDAS = "claude-sonnet-4-5"
            out = r.resolver_modelo_vendas(
                proposito="oferta_conversao",
                analise={"deve_aumentar_ia": False, "score": 20},
            )
        self.assertFalse(out["escalou"])
        self.assertEqual(out["modelo"], "claude-haiku-4-5")

    def test_oferta_escala_com_ads_critico(self):
        with patch.object(r, "restante_orcamento_usd", return_value=5.0), patch.object(
            r, "_cfg"
        ) as cfg:
            cfg.return_value.CLAUDE_ESCALONAR_ML = True
            cfg.return_value.CLAUDE_ESCALONAR_OFERTA = True
            cfg.return_value.CLAUDE_ESCALONAR_OFERTA_SO_CALOR = True
            cfg.return_value.CLAUDE_ESCALONAR_RESTANTE_MIN_USD = 1.5
            cfg.return_value.CLAUDE_MODELO_RAPIDO = "claude-haiku-4-5"
            cfg.return_value.CLAUDE_MODELO_VENDAS = "claude-sonnet-4-5"
            out = r.resolver_modelo_vendas(
                proposito="oferta_conversao",
                sinal_ads={"sustentabilidade": {"status": "critico"}},
                analise={"deve_aumentar_ia": False, "score": 10},
            )
        self.assertTrue(out["escalou"])
        self.assertIn("ads_critico", out["motivo"])

    def test_oferta_modo_legado_sempre_escala(self):
        """CLAUDE_ESCALONAR_OFERTA_SO_CALOR=0 → Sonnet em toda oferta (comportamento antigo)."""
        with patch.object(r, "restante_orcamento_usd", return_value=5.0), patch.object(
            r, "_cfg"
        ) as cfg:
            cfg.return_value.CLAUDE_ESCALONAR_ML = True
            cfg.return_value.CLAUDE_ESCALONAR_OFERTA = True
            cfg.return_value.CLAUDE_ESCALONAR_OFERTA_SO_CALOR = False
            cfg.return_value.CLAUDE_ESCALONAR_RESTANTE_MIN_USD = 1.5
            cfg.return_value.CLAUDE_MODELO_RAPIDO = "claude-haiku-4-5"
            cfg.return_value.CLAUDE_MODELO_VENDAS = "claude-sonnet-4-5"
            out = r.resolver_modelo_vendas(
                proposito="oferta_conversao",
                analise={"deve_aumentar_ia": False, "score": 5},
            )
        self.assertTrue(out["escalou"])
        self.assertEqual(out["modelo"], "claude-sonnet-4-5")
        self.assertTrue(out["forcar_modelo"])

    def test_chat_simples_fica_haiku(self):
        with patch.object(r, "restante_orcamento_usd", return_value=5.0), patch.object(
            r, "_cfg"
        ) as cfg:
            cfg.return_value.CLAUDE_ESCALONAR_ML = True
            cfg.return_value.CLAUDE_ESCALONAR_CHAT = True
            cfg.return_value.CLAUDE_ESCALONAR_PRECO_MIN = 55.0
            cfg.return_value.CLAUDE_ESCALONAR_RESTANTE_MIN_USD = 1.5
            cfg.return_value.CLAUDE_MODELO_RAPIDO = "claude-haiku-4-5"
            cfg.return_value.CLAUDE_MODELO_VENDAS = "claude-sonnet-4-5"
            out = r.resolver_modelo_vendas(
                proposito="chat_ml",
                canal="mercadolivre",
                texto="olá, boa tarde",
                preco_produto=40.0,
                analise={"deve_aumentar_ia": False, "score": 10},
            )
        self.assertFalse(out["escalou"])
        self.assertEqual(out["modelo"], "claude-haiku-4-5")

    def test_chat_intencao_compra_escala(self):
        with patch.object(r, "restante_orcamento_usd", return_value=5.0), patch.object(
            r, "_cfg"
        ) as cfg:
            cfg.return_value.CLAUDE_ESCALONAR_ML = True
            cfg.return_value.CLAUDE_ESCALONAR_CHAT = True
            cfg.return_value.CLAUDE_ESCALONAR_PRECO_MIN = 55.0
            cfg.return_value.CLAUDE_ESCALONAR_RESTANTE_MIN_USD = 1.5
            cfg.return_value.CLAUDE_MODELO_RAPIDO = "claude-haiku-4-5"
            cfg.return_value.CLAUDE_MODELO_VENDAS = "claude-sonnet-4-5"
            out = r.resolver_modelo_vendas(
                proposito="chat_ml",
                canal="mercadolivre",
                texto="Qual o preço no atacado para 10 kits?",
                preco_produto=40.0,
                analise={"deve_aumentar_ia": False, "score": 10},
            )
        self.assertTrue(out["escalou"])
        self.assertIn("intencao_compra_ml", out["motivo"])

    def test_orcamento_baixo_bloqueia_escala(self):
        with patch.object(r, "restante_orcamento_usd", return_value=0.5), patch.object(
            r, "_cfg"
        ) as cfg:
            cfg.return_value.CLAUDE_ESCALONAR_ML = True
            cfg.return_value.CLAUDE_ESCALONAR_OFERTA = True
            cfg.return_value.CLAUDE_ESCALONAR_RESTANTE_MIN_USD = 1.5
            cfg.return_value.CLAUDE_MODELO_RAPIDO = "claude-haiku-4-5"
            cfg.return_value.CLAUDE_MODELO_VENDAS = "claude-sonnet-4-5"
            out = r.resolver_modelo_vendas(proposito="oferta_conversao")
        self.assertFalse(out["escalou"])
        self.assertIn("orcamento_baixo", out["motivo"])

    def test_texto_indica_venda(self):
        self.assertTrue(r.texto_indica_venda("quanto custa o frete Full?"))
        self.assertFalse(r.texto_indica_venda("oi"))


if __name__ == "__main__":
    unittest.main()
