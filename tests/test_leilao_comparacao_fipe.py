"""
tests/test_leilao_comparacao_fipe.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.leilao import comparacao_fipe as cmp


class LeilaoComparacaoFipeTests(unittest.TestCase):
    def test_parse_valor_leilao(self):
        self.assertEqual(cmp.parse_valor_leilao("R$ 9.800,00"), 9800.0)
        self.assertIsNone(cmp.parse_valor_leilao(None))

    def test_calcular_custo_leilao_total(self):
        out = cmp.calcular_custo_leilao_total(
            10000.0,
            comissao_pct=5.0,
            taxa_cadastro_brl=400.0,
            taxa_admin_brl=150.0,
            remocao_estadia_brl=350.0,
            laudo_brl=200.0,
        )
        self.assertEqual(out["comissao_leiloeiro_brl"], 500.0)
        self.assertEqual(out["taxas_fixas_brl"], 1100.0)
        self.assertEqual(out["custo_total_brl"], 11600.0)

    def test_calcular_vantagem_fipe(self):
        v = cmp.calcular_vantagem_fipe(valor_fipe=20000.0, custo_total_brl=11600.0)
        self.assertEqual(v["margem_fipe_reais"], 8400.0)
        self.assertEqual(v["margem_fipe_pct"], 42.0)

    @patch("integracoes.leilao.comparacao_fipe.consultar_preco_fipe")
    def test_avaliar_vantajoso(self, mock_fipe):
        mock_fipe.return_value = {
            "valor_fipe": 25000.0,
            "modelo_fipe": "Uno Mille",
            "ano_fipe": 2012,
        }
        achado = {
            "hash": "x",
            "valor": "R$ 9.800,00",
            "titulo": "Fiat Uno 2012 leilão",
            "marca": "Fiat",
            "modelo": "Uno",
            "ano": 2012,
        }
        veiculo = {"marca": "Fiat", "modelo": "Uno"}
        out = cmp.avaliar_achado_leilao(
            achado,
            veiculo,
            margem_min_pct=25,
            margem_min_reais=3000,
            preco_max_lance=20000,
        )
        self.assertTrue(out["vantajoso"])
        self.assertGreater(out["margem_fipe_pct"], 25)

    @patch("integracoes.leilao.comparacao_fipe.consultar_preco_fipe")
    def test_avaliar_sem_vantagem(self, mock_fipe):
        mock_fipe.return_value = {"valor_fipe": 12000.0}
        out = cmp.avaliar_achado_leilao(
            {"valor": "R$ 11.000,00", "titulo": "Gol", "marca": "VW", "ano": 2015},
            {"marca": "Volkswagen", "modelo": "Gol"},
            margem_min_pct=25,
            margem_min_reais=3000,
        )
        self.assertFalse(out["vantajoso"])

    def test_filtrar_vantajosos(self):
        itens = [{"vantajoso": False, "margem_fipe_pct": 10}, {"vantajoso": True, "margem_fipe_pct": 40}]
        out = cmp.filtrar_vantajosos(itens)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["margem_fipe_pct"], 40)

    def test_aplicar_haircut_fipe_sinistro(self):
        out = cmp.aplicar_haircut_fipe(20000.0, texto_contexto="Fiat Uno recuperado furto", haircut_pct=40)
        self.assertTrue(out["fipe_sinistro"])
        self.assertEqual(out["fipe_haircut_pct"], 40.0)
        self.assertEqual(out["valor_fipe_ajustado"], 12000.0)

    def test_aplicar_haircut_sem_sinistro(self):
        out = cmp.aplicar_haircut_fipe(20000.0, texto_contexto="Fiat Uno leilão", haircut_pct=40)
        self.assertFalse(out["fipe_sinistro"])
        self.assertEqual(out["valor_fipe_ajustado"], 20000.0)

    @patch("integracoes.leilao.comparacao_fipe.consultar_preco_fipe")
    def test_avaliar_aplica_haircut_sinistro(self, mock_fipe):
        mock_fipe.return_value = {
            "valor_fipe": 20000.0,
            "modelo_fipe": "Uno",
            "ano_fipe": 2012,
        }
        with patch.object(cmp, "LEILAO_FIPE_HAIRCUT_SINISTRO_PCT", 40.0):
            out = cmp.avaliar_achado_leilao(
                {
                    "valor": "R$ 5.000,00",
                    "titulo": "Fiat Uno 2012 sinistrado pequena monta",
                    "marca": "Fiat",
                    "ano": 2012,
                },
                {"marca": "Fiat", "modelo": "Uno"},
                margem_min_pct=10,
                margem_min_reais=100,
                preco_max_lance=35000,
            )
        self.assertTrue(out["fipe_sinistro"])
        self.assertEqual(out["valor_fipe"], 12000.0)
        self.assertEqual(out["valor_fipe_tabela"], 20000.0)


if __name__ == "__main__":
    unittest.main()
