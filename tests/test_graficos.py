"""
tests/test_graficos.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import graficos


class GraficosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "g.png"

    def tearDown(self):
        self.tmp.cleanup()

    def test_serie_curta_retorna_none(self):
        out = graficos.grafico_evolucao([{"ts": "x", "v": 1}], [("v", "V")], self.path)
        self.assertIsNone(out)

    @patch.object(graficos, "disponivel", return_value=False)
    def test_sem_matplotlib_retorna_none(self, _mock):
        serie = [{"ts": "a", "v": 1}, {"ts": "b", "v": 2}]
        self.assertIsNone(graficos.grafico_evolucao(serie, [("v", "V")], self.path))
        self.assertIsNone(graficos.grafico_barras(["a"], [1], self.path))

    def test_gera_png_se_matplotlib_disponivel(self):
        if not graficos.disponivel():
            self.skipTest("matplotlib não instalado")
        serie = [
            {"ts": "2026-07-01T10:00:00+00:00", "v": 10, "w": 5},
            {"ts": "2026-07-01T16:00:00+00:00", "v": 20, "w": 8},
            {"ts": "2026-07-02T10:00:00+00:00", "v": 15, "w": 12},
        ]
        out = graficos.grafico_evolucao(serie, [("v", "V"), ("w", "W")], self.path, titulo="Teste")
        self.assertIsNotNone(out)
        self.assertTrue(os.path.exists(self.path))
        self.assertGreater(os.path.getsize(self.path), 0)

    def test_grafico_evolucao_campo_unico(self):
        if not graficos.disponivel():
            self.skipTest("matplotlib não instalado")
        serie = [{"ts": "a", "v": 1}, {"ts": "b", "v": None}, {"ts": "c", "v": 3}]
        out = graficos.grafico_evolucao(serie, [("v", "V")], self.path)
        self.assertIsNotNone(out)
        self.assertTrue(os.path.exists(self.path))

    def test_grafico_barras_gera_png(self):
        if not graficos.disponivel():
            self.skipTest("matplotlib não instalado")
        out = graficos.grafico_barras(
            ["Impala", "Anita", "Risqué"],
            [3000, 1500, 800],
            self.path,
            titulo="Ranking marcas",
            rotulo_x="vendas",
        )
        self.assertIsNotNone(out)
        self.assertTrue(os.path.exists(self.path))
        self.assertGreater(os.path.getsize(self.path), 0)

    def test_grafico_barras_entrada_invalida(self):
        self.assertIsNone(graficos.grafico_barras([], [], self.path))
        self.assertIsNone(graficos.grafico_barras(["a", "b"], [1], self.path))


if __name__ == "__main__":
    unittest.main()
