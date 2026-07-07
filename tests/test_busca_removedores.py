"""
tests/test_busca_removedores.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import busca_removedores as br


class BuscaRemovedoresTests(unittest.TestCase):
    def test_termos_cascata_inclui_fallbacks(self):
        segmento = {
            "id": "cruzeiro",
            "marca": "cruzeiro",
            "termo_busca": "removedor esmalte cruzeiro acetona",
            "termos_alternativos": ["acetona cruzeiro manicure"],
        }
        termos = br._termos_busca_segmento(segmento)
        self.assertIn("acetona cruzeiro", termos)
        self.assertTrue(any("removedor cruzeiro" in t for t in termos))

    def test_buscar_segmento_cascata(self):
        segmento = {
            "id": "impala",
            "marca": "impala",
            "termo_busca": "termo longo sem resultado",
            "termos_alternativos": [],
            "limite_resultados": 10,
        }
        chamadas: list[str] = []

        def _buscar(termo: str, **kwargs: object) -> list[dict]:
            chamadas.append(termo)
            if "impala" in termo.lower():
                return [
                    {
                        "item_id": "MLB1",
                        "titulo": "Acetona Impala 100ml profissional",
                        "preco": 11.0,
                        "quantidade_vendida": 80,
                    }
                ]
            return []

        produtos, termo_usado, bruto = br.buscar_removedores_segmento(segmento, _buscar)
        self.assertEqual(len(produtos), 1)
        self.assertIn("impala", termo_usado.lower())
        self.assertGreater(len(chamadas), 1)


if __name__ == "__main__":
    unittest.main()
