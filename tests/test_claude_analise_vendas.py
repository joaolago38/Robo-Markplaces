"""tests/test_claude_analise_vendas.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core import claude_analise_vendas as a
from core import claude_roteador as r


class TestAnaliseVendas(unittest.TestCase):
    def _cfg(self, **kwargs):
        cfg = patch.object(a, "_cfg")
        mock = cfg.start()
        self.addCleanup(cfg.stop)
        mock.return_value.CLAUDE_ANALISE_SCORE_ALTO = 70
        mock.return_value.CLAUDE_ANALISE_SCORE_MEDIO = 40
        mock.return_value.CLAUDE_ANALISE_SCORE_ALTO_CAPTACAO = 85
        mock.return_value.CLAUDE_ANALISE_GASTO_META_PRESSAO = 30
        mock.return_value.CLAUDE_ESCALONAR_PRECO_MIN = 55
        for k, v in kwargs.items():
            setattr(mock.return_value, k, v)
        return mock

    def test_oi_ml_medio_ou_baixo(self):
        self._cfg()
        out = a.analisar_oportunidade_ml(
            texto="oi",
            canal="mercadolivre",
            preco_produto=40,
            proposito="chat_ml",
        )
        self.assertEqual(out["papel"], "fechamento_ml")
        self.assertEqual(out["termometro_principal"], "mercado_livre")
        self.assertIn(out["nivel"], ("baixo", "medio"))
        self.assertFalse(out["deve_aumentar_ia"])

    def test_chat_ml_atacado_alto(self):
        self._cfg()
        out = a.analisar_oportunidade_ml(
            texto="Quero comprar no atacado 10 kits, qual o melhor preço?",
            canal="mercadolivre",
            preco_produto=69.9,
            estoque=3,
            proposito="chat_ml",
        )
        self.assertEqual(out["papel"], "fechamento_ml")
        self.assertEqual(out["nivel"], "alto")
        self.assertTrue(out["deve_aumentar_ia"])

    def test_captacao_ig_exige_mais_para_sonnet(self):
        self._cfg()
        out = a.analisar_oportunidade_ml(
            texto="quanto custa?",
            canal="instagram",
            proposito="resposta_lead",
            converter=True,
            intencao="interesse",
        )
        self.assertEqual(out["papel"], "captacao_meta")
        # limiar 85 — interesse sozinho não deve forçar Sonnet
        self.assertFalse(out["deve_aumentar_ia"])

    def test_pressao_ads_sobe_fechamento_ml(self):
        self._cfg()
        out = a.analisar_oportunidade_ml(
            texto="tem frete full pro meu cep?",
            canal="mercadolivre",
            proposito="chat_ml",
            preco_produto=60,
            sinal_ads={
                "gasto": 80,
                "compras": 2,
                "status_sustentavel": "alerta",
                "roas_real": 1.1,
                "sustentabilidade": {"status": "alerta", "roas_real": 1.1},
            },
        )
        self.assertEqual(out["papel"], "fechamento_ml")
        self.assertTrue(out["deve_aumentar_ia"])
        self.assertTrue(any("captacao_meta_gasto" in f or "pressao_ads" in f for f in out["fatores"]))

    def test_roteador_usa_analise_alta(self):
        analise = {
            "ok": True,
            "score": 82,
            "nivel": "alto",
            "deve_aumentar_ia": True,
            "papel": "fechamento_ml",
            "resumo": "alto",
            "fatores": ["x"],
        }
        with patch.object(r, "restante_orcamento_usd", return_value=5.0), patch.object(
            r, "_cfg"
        ) as cfg:
            cfg.return_value.CLAUDE_ESCALONAR_ML = True
            cfg.return_value.CLAUDE_ESCALONAR_RESTANTE_MIN_USD = 1.5
            cfg.return_value.CLAUDE_ESCALONAR_OFERTA = False
            cfg.return_value.CLAUDE_ESCALONAR_CHAT = False
            cfg.return_value.CLAUDE_MODELO_RAPIDO = "claude-haiku-4-5"
            cfg.return_value.CLAUDE_MODELO_VENDAS = "claude-sonnet-4-5"
            out = r.resolver_modelo_vendas(
                proposito="chat_ml",
                canal="mercadolivre",
                texto="x",
                analise=analise,
            )
        self.assertTrue(out["escalou"])
        self.assertIn("analise_alta", out["motivo"])


if __name__ == "__main__":
    unittest.main()
