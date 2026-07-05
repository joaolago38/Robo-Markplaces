import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.precificacao_comportamento import calcular_lucro_operacao, calcular_preco_ideal


class PrecificacaoComportamentoTests(unittest.TestCase):
    def test_respeita_piso_margem(self):
        out = calcular_preco_ideal(
            preco_atual=50.0,
            custo=30.0,
            preco_concorrente=25.0,
            margem_minima_pct=10.0,
            taxa_canal_pct=18.0,
            abaixo_concorrente_pct=3.0,
        )
        self.assertGreaterEqual(out["preco_sugerido"], out["preco_piso"])
        self.assertGreaterEqual(out["margem_pct"], 10.0)

    def test_desconto_quando_visitas_sem_venda(self):
        out = calcular_preco_ideal(
            preco_atual=50.0,
            custo=20.0,
            preco_concorrente=None,
            margem_minima_pct=10.0,
            taxa_canal_pct=18.0,
            abaixo_concorrente_pct=3.0,
            sinais={"visitas_7d": 30, "visitas_30d": 40, "unidades_vendidas_7d": 0},
        )
        self.assertLess(out["preco_sugerido"], 50.0)
        self.assertIn("reduzir", out["acao"].lower())

    def test_aumento_demanda_forte(self):
        out = calcular_preco_ideal(
            preco_atual=50.0,
            custo=20.0,
            preco_concorrente=None,
            margem_minima_pct=10.0,
            taxa_canal_pct=18.0,
            abaixo_concorrente_pct=3.0,
            sinais={"visitas_7d": 10, "unidades_vendidas_7d": 5},
        )
        self.assertGreater(out["preco_sugerido"], 50.0)

    def test_usa_sugestao_ml_quando_disponivel(self):
        out = calcular_preco_ideal(
            preco_atual=60.0,
            custo=25.0,
            preco_concorrente=None,
            margem_minima_pct=10.0,
            taxa_canal_pct=18.0,
            abaixo_concorrente_pct=3.0,
            sinais={"preco_sugerido_ml": 55.0},
        )
        self.assertEqual(out["preco_sugerido"], 55.0)

    def test_trafego_caindo_monitora(self):
        out = calcular_preco_ideal(
            preco_atual=50.0,
            custo=20.0,
            preco_concorrente=None,
            margem_minima_pct=10.0,
            taxa_canal_pct=18.0,
            abaixo_concorrente_pct=3.0,
            sinais={"visitas_7d": 7, "visitas_30d": 90, "unidades_vendidas_7d": 0},
        )
        self.assertIn("caindo", out["comportamento"])

    def test_lider_vende_mais_com_preco_similar(self):
        out = calcular_preco_ideal(
            preco_atual=50.0,
            custo=20.0,
            preco_concorrente=49.0,
            margem_minima_pct=10.0,
            taxa_canal_pct=18.0,
            abaixo_concorrente_pct=3.0,
            sinais={"quantidade_vendida_lider": 20, "unidades_vendidas_7d": 1},
        )
        self.assertLessEqual(out["preco_sugerido"], 50.0)

    def test_lucro_operacao_desconta_taxa_canal(self):
        lucro = calcular_lucro_operacao(59.90, 34.44, 18.0)
        self.assertAlmostEqual(lucro["lucro_reais"], 14.68, places=1)
        self.assertGreater(lucro["margem_operacional_pct"], 20.0)

    def test_preco_ideal_inclui_lucro_operacao(self):
        out = calcular_preco_ideal(
            preco_atual=59.90,
            custo=34.44,
            preco_concorrente=52.0,
            margem_minima_pct=10.0,
            taxa_canal_pct=18.0,
            abaixo_concorrente_pct=3.0,
        )
        self.assertIn("lucro_operacao", out)
        self.assertGreater(out["lucro_operacao"]["sugerido_reais"], 0)
        self.assertTrue(out["lucro_operacao"]["lucro_ok"])


if __name__ == "__main__":
    unittest.main()
