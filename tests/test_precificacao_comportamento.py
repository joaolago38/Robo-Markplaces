import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.precificacao_comportamento import calcular_preco_ideal


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


if __name__ == "__main__":
    unittest.main()
