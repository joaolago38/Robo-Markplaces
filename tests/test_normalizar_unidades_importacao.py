"""
tests/test_normalizar_unidades_importacao.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.importacao.normalizar_unidades import (
    custo_para_comparacao_marketplace,
    normalizar_preco_usd,
)


class NormalizarUnidadesTests(unittest.TestCase):
    def test_normalizar_preco_por_100_pecas(self):
        produto = {"unidade_por_preco": 100, "unidade_rotulo": "100 peças"}
        out = normalizar_preco_usd(produto, 0.80)
        self.assertEqual(out["preco_usd_listing"], 0.80)
        self.assertAlmostEqual(out["preco_usd_unit"], 0.008, places=4)
        self.assertEqual(out["unidade_por_preco"], 100)

    def test_custo_pack_marketplace(self):
        produto = {"unidade_marketplace_qtd": 100}
        self.assertEqual(custo_para_comparacao_marketplace(0.05, produto), 5.0)


if __name__ == "__main__":
    unittest.main()
