"""
tests/test_busca_kit_frequencia.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import busca_kit_frequencia as bkf


class BuscaKitFrequenciaTests(unittest.TestCase):
    def test_termos_busca_item_inclui_alternativos(self):
        item = {
            "termo_busca": "kit 3 esmaltes anita classico",
            "termos_alternativos": ["kit 3 esmaltes anita"],
            "marca": "anita",
            "qtd_esmaltes": 3,
        }
        termos = bkf._termos_busca_item(item)
        self.assertIn("kit 3 esmaltes anita classico", termos)
        self.assertIn("kit 3 esmaltes anita", termos)
        self.assertTrue(any("manicure" in t for t in termos))

    def test_filtrar_anuncios_tolerancia_imprecisos(self):
        item = {
            "marca": "anita",
            "qtd_esmaltes": 3,
            "cores_busca": ["nude", "rosa"],
        }
        anuncios = [
            {"titulo": "Kit 3 esmaltes Anita nude", "item_id": "1"},
            {"titulo": "Kit 3 esmaltes Risque sortido manicure", "item_id": "2"},
            {"titulo": "Caneta esferográfica azul", "item_id": "3"},
        ]
        out = bkf._filtrar_anuncios(item, anuncios, limite=10, tolerancia_erro=0.10)
        titulos = [a["titulo"] for a in out]
        self.assertIn("Kit 3 esmaltes Anita nude", titulos)
        self.assertNotIn("Caneta esferográfica azul", titulos)

    def test_buscar_anuncios_item_cascata(self):
        item = {
            "id": "kit3-anita",
            "termo_busca": "termo restrito xyz",
            "termos_alternativos": ["kit 3 esmaltes anita"],
            "marca": "anita",
            "qtd_esmaltes": 3,
            "cores_busca": ["nude"],
            "limite_resultados": 10,
        }
        chamadas: list[str] = []

        def _buscar(termo: str, **kwargs: object) -> list[dict]:
            chamadas.append(termo)
            if "anita" in termo:
                return [{"titulo": "Kit 3 esmaltes Anita nude", "item_id": "MLB1"}]
            return []

        anuncios, termo_usado = bkf.buscar_anuncios_item(item, _buscar)
        self.assertEqual(len(anuncios), 1)
        self.assertIn("anita", termo_usado)
        self.assertGreater(len(chamadas), 1)

    def test_executar_busca_item_conta_cores(self):
        item = {
            "id": "kit3-anita",
            "nome": "Kit 3 Anita",
            "marca": "anita",
            "cor_foco": "Nude",
            "cores_busca": ["nude", "rosa", "vermelho"],
            "termo_busca": "kit 3 esmalte anita nude",
        }
        anuncios = [
            {"titulo": "Kit 3 esmaltes Anita nude rosa manicure", "preco": 29.9},
            {"titulo": "Esmalte Anita vermelho classico", "preco": 19.9},
            {"titulo": "Kit impala sortido", "preco": 49.0},
        ]
        out = bkf.executar_busca_item(item, anuncios, timestamp="2026-07-06T12:00:00+00:00")
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_anuncios"], 3)
        self.assertGreaterEqual(out["anuncios_da_marca"], 2)
        self.assertIn("nude", {k.lower() for k in out["cores_encontradas"]})
        self.assertEqual(out["com_preco"], 3)
        self.assertAlmostEqual(out["preco_min"], 19.9)
        self.assertAlmostEqual(out["preco_max"], 49.0)
        self.assertAlmostEqual(out["preco_min_marca"], 19.9)
        self.assertAlmostEqual(out["preco_max_marca"], 29.9)

    def test_resumo_precos_vazio(self):
        out = bkf._resumo_precos([{"titulo": "x", "preco": 0}], marca_esperada="anita")
        self.assertEqual(out["com_preco"], 0)
        self.assertEqual(out["preco_medio"], 0.0)

    def test_registrar_execucao_diaria(self):
        historico: dict = {}
        resultado = {
            "item_id": "kit5-impala",
            "nome": "Kit 5 Impala",
            "marca": "impala",
            "cor_foco": "Rosa",
            "termo_busca": "kit 5 esmalte impala",
            "timestamp": "2026-07-06T12:00:00+00:00",
            "total_anuncios": 10,
            "cores_encontradas": {"rosa": 4, "nude": 2},
            "com_preco": 5,
            "com_preco_marca": 5,
            "preco_min": 20.0,
            "preco_medio": 30.0,
            "preco_max": 40.0,
            "preco_min_marca": 20.0,
            "preco_medio_marca": 30.0,
            "preco_max_marca": 40.0,
        }
        dia = bkf.registrar_execucao_diaria(historico, resultado, dia="2026-07-06")
        self.assertEqual(dia["total_buscas"], 1)
        self.assertEqual(dia["impala"], 1)
        self.assertEqual(dia["itens"]["kit5-impala"]["buscas"], 1)
        self.assertEqual(dia["itens"]["kit5-impala"]["cores_encontradas"]["rosa"], 4)
        self.assertAlmostEqual(dia["itens"]["kit5-impala"]["preco_min"], 20.0)
        self.assertAlmostEqual(dia["itens"]["kit5-impala"]["preco_medio"], 30.0)

        bkf.registrar_execucao_diaria(
            historico,
            {
                **resultado,
                "marca": "anita",
                "item_id": "kit5-anita",
                "preco_min_marca": 15.0,
                "preco_medio_marca": 25.0,
                "preco_max_marca": 35.0,
            },
            dia="2026-07-06",
        )
        self.assertEqual(historico["2026-07-06"]["total_buscas"], 2)

        # Segunda rodada do mesmo kit amplia min/máx
        bkf.registrar_execucao_diaria(
            historico,
            {
                **resultado,
                "preco_min_marca": 18.0,
                "preco_medio_marca": 50.0,
                "preco_max_marca": 55.0,
                "com_preco_marca": 2,
            },
            dia="2026-07-06",
        )
        kit = historico["2026-07-06"]["itens"]["kit5-impala"]
        self.assertAlmostEqual(kit["preco_min"], 18.0)
        self.assertAlmostEqual(kit["preco_max"], 55.0)

    def test_consolidar_dia(self):
        dia_obj = {
            "total_buscas": 4,
            "anita": 2,
            "impala": 2,
            "itens": {
                "a": {"cores_encontradas": {"nude": 3, "rosa": 1}},
                "b": {"cores_encontradas": {"nude": 2, "vermelho": 5}},
            },
        }
        c = bkf.consolidar_dia(dia_obj)
        self.assertEqual(c["total_buscas"], 4)
        top = {t["cor"]: t["mencoes"] for t in c["top_cores"]}
        self.assertEqual(top.get("nude"), 5)
        self.assertEqual(top.get("vermelho"), 5)


if __name__ == "__main__":
    unittest.main()
