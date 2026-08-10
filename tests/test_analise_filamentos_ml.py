"""
tests/test_analise_filamentos_ml.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.filamentos import analise_filamentos_ml as af


class AnaliseFilamentosMlTests(unittest.TestCase):
    def test_detectar_marca_e_material(self):
        self.assertEqual(af.detectar_marca("eSUN Filamento PLA 1kg 1.75mm"), "eSUN")
        self.assertEqual(af.detectar_material("Filamento PETG preto 1kg"), "PETG")
        self.assertEqual(af.detectar_material("Filamento TPU flexivel 1kg"), "TPU")
        self.assertEqual(af.detectar_material("Filamento ABS Creality 1kg"), "ABS")
        self.assertEqual(af.detectar_peso_kg("Filamento PLA 1kg"), 1.0)

    def test_filtra_por_material_esperado(self):
        self.assertTrue(af.eh_listing_filamento("Filamento PLA preto 1kg", "PLA"))
        self.assertFalse(af.eh_listing_filamento("Filamento ABS preto 1kg", "PLA"))
        self.assertTrue(af.eh_listing_filamento("Filamento TPU flexivel 1kg", "TPU"))
        self.assertTrue(af.eh_listing_filamento("Filamento PETG 1kg", "PETG"))
        self.assertTrue(af.eh_listing_filamento("Filamento ABS 1kg", "ABS"))

    def test_detectar_cores(self):
        self.assertEqual(af.detectar_cor_principal("Filamento PLA preto 1kg"), "Preto")
        self.assertIn("Branco", af.detectar_cores("Filamento PLA white 1kg"))
        self.assertEqual(af.cor_para_termo_en("Preto"), "black")

    def test_filtra_nao_filamento(self):
        self.assertFalse(af.eh_listing_filamento("Curso impressora 3D"))
        self.assertTrue(af.eh_listing_filamento("Filamento PLA 1kg Creality"))

    def test_processar_e_consolidar(self):
        seg = {
            "id": "fil-pla",
            "nome": "PLA",
            "material": "PLA",
            "termo_busca": "filamento pla",
            "prioridade": 1,
        }
        anuncios = [
            {
                "item_id": "MLB1",
                "titulo": "eSUN Filamento PLA preto 1kg 1.75mm",
                "preco": 89.9,
                "quantidade_vendida": 500,
            },
            {
                "item_id": "MLB2",
                "titulo": "Filamento ABS Creality 1kg",
                "preco": 99.0,
                "quantidade_vendida": 50,
            },
            {
                "item_id": "MLB3",
                "titulo": "Curso de impressão 3D",
                "preco": 29.0,
                "quantidade_vendida": 10,
            },
            {
                "item_id": "MLB4",
                "titulo": "Printalot Filamento PLA branco 1kg",
                "preco": 79.0,
                "quantidade_vendida": 200,
            },
        ]
        out = af.processar_termo(seg, anuncios)
        self.assertEqual(out["total_filamentos"], 2)
        self.assertEqual(out["produtos"][0]["cor"], "Preto")

        cons = af.consolidar_varredura([out])
        self.assertEqual(cons["total_filamentos_unicos"], 2)
        self.assertEqual(cons["ranking_cores"][0]["cor"], "Preto")
        self.assertEqual(cons["ranking_marcas"][0]["marca"], "eSUN")

    def test_ranking_sem_vendas_api_usa_presenca(self):
        produtos = [
            af.classificar_anuncio(
                {
                    "item_id": "MLB1",
                    "titulo": "Filamento PETG preto 1kg",
                    "preco": 120,
                    "quantidade_vendida": 0,
                },
                material_esperado="PETG",
            ),
            af.classificar_anuncio(
                {
                    "item_id": "MLB2",
                    "titulo": "Filamento PETG preto 1kg Creality",
                    "preco": 130,
                    "quantidade_vendida": 0,
                },
                material_esperado="PETG",
            ),
            af.classificar_anuncio(
                {
                    "item_id": "MLB3",
                    "titulo": "eSUN Filamento PETG azul 1kg",
                    "preco": 140,
                    "quantidade_vendida": 0,
                    "avaliacoes": 50,
                },
                material_esperado="PETG",
            ),
        ]
        produtos = [p for p in produtos if p]
        cores = af.ranking_cores(produtos)
        self.assertEqual(cores[0]["vendidos"], 0)
        # Azul com avaliações deve pesar mais que Preto só por presença
        self.assertEqual(cores[0]["cor"], "Azul")
        marcas = af._ranking(produtos, "marca")
        self.assertEqual(marcas[0]["marca"], "eSUN")
        self.assertEqual(af.fmt_vendas_amostra(0), "n/d")
        self.assertEqual(af.fmt_vendas_amostra(10), "10 vendas")

    def test_fmt_vendas_amostra(self):
        self.assertEqual(af.fmt_vendas_amostra(0), "n/d")
        self.assertEqual(af.fmt_vendas_amostra(12), "12 vendas")


if __name__ == "__main__":
    unittest.main()
