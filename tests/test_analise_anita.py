"""
tests/test_analise_anita.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import analise_anita as aa


class AnaliseAnitaTests(unittest.TestCase):
    def test_detectar_marca(self):
        self.assertEqual(aa.detectar_marca("Kit 5 Esmaltes Anita Nude"), "Anita")
        self.assertEqual(aa.detectar_marca("Kit Impala Bailarina"), "Impala")

    def test_extrair_qtd_kit(self):
        self.assertEqual(aa.extrair_qtd_kit("Kit 10 Esmaltes Anita Atacado"), 10)
        self.assertEqual(aa.extrair_qtd_kit("Esmalte unitário"), None)

    def test_comparar_preferencia_kit(self):
        produto = {
            "tipo": "kit",
            "qtd_esmaltes_preferencia": 5,
            "cores_preferencia": ["Nude", "Bege"],
            "meu_preco": 48.90,
            "custo_total": 24.0,
            "taxa_marketplace_pct": 18,
        }
        anuncio = {"titulo": "Kit 3 Esmaltes Anita Nude Bege", "preco": 42.0}
        out = aa.comparar_preferencia(produto, anuncio)
        self.assertEqual(out["diff_qtd_kit"], -2)
        self.assertFalse(out["kit_conforme_preferencia"])
        self.assertIn("Nude", out["cores_encontradas"])

    def test_ranking_marcas(self):
        anuncios = [
            {"titulo": "Kit Anita 5 cores", "quantidade_vendida": 100, "preco": 50},
            {"titulo": "Kit Impala 5", "quantidade_vendida": 200, "preco": 45},
            {"titulo": "Anita Avoante", "quantidade_vendida": 80, "preco": 10},
        ]
        rank = aa.ranking_marcas(anuncios)
        self.assertEqual(rank[0]["marca"], "Impala")
        self.assertEqual(rank[0]["vendidos"], 200)

    def test_analisar_produto(self):
        produto = {
            "id": "p1",
            "nome": "Kit 5 Anita",
            "tipo": "kit",
            "termo_busca": "kit anita",
            "qtd_esmaltes_preferencia": 5,
            "cores_preferencia": ["Nude"],
            "meu_preco": 50.0,
            "custo_total": 25.0,
            "taxa_marketplace_pct": 18,
        }
        anuncios = [
            {"titulo": "Kit 5 Esmaltes Anita Nude", "preco": 48.0, "quantidade_vendida": 30},
            {"titulo": "Kit 5 Impala", "preco": 44.0, "quantidade_vendida": 50},
        ]
        out = aa.analisar_produto(produto, anuncios)
        self.assertEqual(out["total_anita"], 1)
        self.assertEqual(out["total_impala"], 1)
        self.assertEqual(out["unidades_vendidas_impala"], 50)
        self.assertTrue(out["impala_lider_vendas"])
        self.assertAlmostEqual(out["share_impala_pct"], 50 / 80 * 100, places=1)
        self.assertIn("margem_minha", out)


if __name__ == "__main__":
    unittest.main()
