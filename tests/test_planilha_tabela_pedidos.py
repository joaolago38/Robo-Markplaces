# -*- coding: utf-8 -*-
"""tests/test_planilha_tabela_pedidos.py"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.masterprint import planilha_tabela_pedidos as tp

PLANILHA = (
    Path(__file__).resolve().parents[1]
    / "planilhas_ecommerce"
    / "TABELA DE PEDIDOS.XLSX"
)


@unittest.skipUnless(PLANILHA.is_file(), "TABELA DE PEDIDOS.XLSX ausente")
class TestTabelaPedidos(unittest.TestCase):
    def test_parse_filamentos_e_escritorio(self):
        out = tp.parse_tabela_pedidos(PLANILHA)
        self.assertTrue(out["ok"], out.get("erro"))
        tot = out["totais"]
        self.assertGreater(tot["filamentos"], 50)
        self.assertGreater(tot["escritorio"], 5)
        mats = set(out["por_material"])
        self.assertTrue({"PLA", "PETG"} <= mats)
        self.assertIn("pincel_permanente", mats)
        self.assertIn("apagador", mats)


if __name__ == "__main__":
    unittest.main()
