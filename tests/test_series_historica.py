"""
tests/test_series_historica.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import series_historica as sh


class SeriesHistoricaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "serie.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_registrar_ponto_anexa_e_trunca(self):
        for i in range(5):
            serie = sh.registrar_ponto(self.path, {"total": i}, max_pontos=3)
        self.assertEqual(len(serie), 3)
        self.assertEqual([p["total"] for p in serie], [2, 3, 4])
        self.assertIn("ts", serie[-1])

    def test_variacao_calcula_delta_e_pct(self):
        sh.registrar_ponto(self.path, {"total": 100})
        serie = sh.registrar_ponto(self.path, {"total": 150})
        var = sh.variacao(serie, "total")
        self.assertEqual(var["atual"], 150)
        self.assertEqual(var["anterior"], 100)
        self.assertEqual(var["delta"], 50)
        self.assertEqual(var["pct"], 50.0)

    def test_variacao_sem_anterior(self):
        serie = sh.registrar_ponto(self.path, {"total": 10})
        var = sh.variacao(serie, "total")
        self.assertEqual(var["atual"], 10)
        self.assertIsNone(var["anterior"])
        self.assertIsNone(var["delta"])

    def test_sparkline(self):
        spark = sh.sparkline([1, 2, 3, 4, 5])
        self.assertEqual(len(spark), 5)
        self.assertEqual(sh.sparkline([]), "")

    def test_seta(self):
        self.assertEqual(sh.seta(5), "🔺")
        self.assertEqual(sh.seta(-5), "🔻")
        self.assertEqual(sh.seta(0), "▪️")
        self.assertEqual(sh.seta(None), "•")

    def test_formatar_comparativo(self):
        sh.registrar_ponto(self.path, {"vendas": 100, "preco": 10.0})
        serie = sh.registrar_ponto(self.path, {"vendas": 120, "preco": 12.5})
        txt = sh.formatar_comparativo(serie, [("vendas", "Vendas"), ("preco", "Preço médio", 2)])
        self.assertIn("Comparativo", txt)
        self.assertIn("Vendas", txt)
        self.assertIn("🔺", txt)


if __name__ == "__main__":
    unittest.main()
