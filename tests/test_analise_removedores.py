"""
tests/test_analise_removedores.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import analise_removedores as ar


class AnaliseRemovedoresTests(unittest.TestCase):
    def test_detectar_fabricante(self):
        self.assertEqual(ar.detectar_fabricante("Removedor Acetona Cruzeiro 500ml"), "Cruzeiro")
        self.assertEqual(ar.detectar_fabricante("Acetona Impala profissional 100ml"), "Impala")

    def test_processar_termo_filtra_removedores(self):
        segmento = {"id": "geral", "nome": "Geral", "termo_busca": "removedor esmalte"}
        anuncios = [
            {
                "titulo": "Removedor Acetona Cruzeiro 100ml profissional",
                "item_id": "MLB1",
                "preco": 12.0,
                "quantidade_vendida": 500,
            },
            {"titulo": "Esmalte Anita vermelho", "item_id": "MLB2", "preco": 8.0, "quantidade_vendida": 100},
        ]
        out = ar.processar_termo(segmento, anuncios)
        self.assertEqual(out["total_removedores"], 1)
        self.assertEqual(out["produtos"][0]["fabricante"], "Cruzeiro")

    def test_consolidar_ranking_fabricantes(self):
        resultados = [
            {
                "ok": True,
                "produtos": [
                    {
                        "item_id": "MLB1",
                        "titulo": "Removedor Cruzeiro 500ml",
                        "nome_produto": "Removedor Cruzeiro 500ml",
                        "fabricante": "Cruzeiro",
                        "preco": 28.0,
                        "quantidade_vendida": 800,
                        "volume_ml": 500,
                    },
                    {
                        "item_id": "MLB2",
                        "titulo": "Acetona Impala 100ml",
                        "nome_produto": "Acetona Impala 100ml",
                        "fabricante": "Impala",
                        "preco": 10.0,
                        "quantidade_vendida": 200,
                        "volume_ml": 100,
                    },
                ],
            }
        ]
        c = ar.consolidar_varredura(resultados)
        self.assertEqual(c["total_produtos_unicos"], 2)
        self.assertEqual(c["ranking_fabricantes"][0]["fabricante"], "Cruzeiro")
        self.assertEqual(c["ranking_fabricantes"][0]["rank"], 1)
        self.assertEqual(c["top_vendas"][0]["item_id"], "MLB1")


if __name__ == "__main__":
    unittest.main()
