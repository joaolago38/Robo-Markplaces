"""
tests/test_analise_kits_esmaltes.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import analise_kits_esmaltes as ake


class AnaliseKitsEsmaltesTests(unittest.TestCase):
    def test_processar_termo_filtra_somente_kits(self):
        segmento = {"id": "kit5", "nome": "Kit 5", "termo_busca": "kit 5 esmaltes"}
        anuncios = [
            {"titulo": "Kit 5 esmaltes Impala bailarina", "item_id": "MLB1", "preco": 48.0, "quantidade_vendida": 120},
            {"titulo": "Esmalte Anita unitário vermelho", "item_id": "MLB2", "preco": 8.0, "quantidade_vendida": 50},
        ]
        out = ake.processar_termo(segmento, anuncios)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_bruto"], 2)
        self.assertEqual(out["total_kits"], 1)
        self.assertEqual(out["kits"][0]["item_id"], "MLB1")

    def test_consolidar_varredura_deduplica_e_rankeia(self):
        resultados = [
            {
                "ok": True,
                "kits": [
                    {
                        "item_id": "MLB1",
                        "titulo": "Kit 10 Impala atacado",
                        "marca": "Impala",
                        "preco": 69.0,
                        "quantidade_vendida": 200,
                        "qtd_kit": 10,
                        "tipo_anuncio": "kit",
                    },
                    {
                        "item_id": "MLB2",
                        "titulo": "Kit 5 Anita nude",
                        "marca": "Anita",
                        "preco": 45.0,
                        "quantidade_vendida": 80,
                        "qtd_kit": 5,
                        "tipo_anuncio": "kit",
                    },
                ],
            },
            {
                "ok": True,
                "kits": [
                    {
                        "item_id": "MLB1",
                        "titulo": "Kit 10 Impala atacado",
                        "marca": "Impala",
                        "preco": 69.0,
                        "quantidade_vendida": 250,
                        "qtd_kit": 10,
                        "tipo_anuncio": "kit",
                    },
                ],
            },
        ]
        c = ake.consolidar_varredura(resultados)
        self.assertEqual(c["total_kits_unicos"], 2)
        self.assertEqual(c["total_vendas"], 330)
        self.assertEqual(c["ranking_marcas"][0]["marca"], "Impala")
        self.assertEqual(c["top_vendas"][0]["item_id"], "MLB1")


if __name__ == "__main__":
    unittest.main()
