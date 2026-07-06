"""
tests/test_busca_kit_frequencia.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import busca_kit_frequencia as bkf


class BuscaKitFrequenciaTests(unittest.TestCase):
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
            {"titulo": "Kit 3 esmaltes Anita nude rosa manicure"},
            {"titulo": "Esmalte Anita vermelho classico"},
            {"titulo": "Kit impala sortido"},
        ]
        out = bkf.executar_busca_item(item, anuncios, timestamp="2026-07-06T12:00:00+00:00")
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_anuncios"], 3)
        self.assertGreaterEqual(out["anuncios_da_marca"], 2)
        self.assertIn("nude", {k.lower() for k in out["cores_encontradas"]})

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
        }
        dia = bkf.registrar_execucao_diaria(historico, resultado, dia="2026-07-06")
        self.assertEqual(dia["total_buscas"], 1)
        self.assertEqual(dia["impala"], 1)
        self.assertEqual(dia["itens"]["kit5-impala"]["buscas"], 1)
        self.assertEqual(dia["itens"]["kit5-impala"]["cores_encontradas"]["rosa"], 4)

        bkf.registrar_execucao_diaria(historico, {**resultado, "marca": "anita"}, dia="2026-07-06")
        self.assertEqual(historico["2026-07-06"]["total_buscas"], 2)

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
