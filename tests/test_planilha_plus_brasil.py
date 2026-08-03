"""
tests/test_planilha_plus_brasil.py
Parser PLUS BRASIL + comparação com custo_landed (deltas AFRMM/Siscomex).
"""
from __future__ import annotations

import unittest
from pathlib import Path

from core.config import ROOT
from integracoes.importacao import custo_landed as cl
from integracoes.importacao import planilha_plus_brasil as plus
from integracoes.importacao.siscomex import taxa_siscomex_brl

PLANILHA = ROOT / "dados" / "importacao_simula_plus_brasil.xlsx"


class PlanilhaPlusBrasilTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PLANILHA.exists():
            raise unittest.SkipTest(f"planilha ausente: {PLANILHA}")

    def test_parse_cif_ii_despesas(self):
        p = plus.parsear_planilha_plus(PLANILHA)
        self.assertTrue(p["ok"], p.get("motivo"))
        self.assertAlmostEqual(p["cif_brl"], 23687.5, places=1)
        self.assertAlmostEqual(p["cambio_usd_brl"], 3.79, places=2)
        self.assertAlmostEqual(p["vmle_usd"], 6000.0, places=1)
        self.assertAlmostEqual(p["frete_internacional_usd"], 250.0, places=1)
        self.assertEqual(p["ncm"], "9016.60.00")
        self.assertAlmostEqual(p["aliquotas"]["ii_pct"], 14.0, places=1)
        self.assertAlmostEqual(p["aliquotas"]["pis_pct"], 2.1, places=2)
        self.assertAlmostEqual(p["aliquotas"]["cofins_pct"], 9.65, places=2)
        self.assertAlmostEqual(p["aliquotas"]["icms_pct"], 18.0, places=1)
        self.assertIn("armazenagem_zp", p["outras_despesas"])
        self.assertGreater(p["outras_despesas"]["armazenagem_zp"], 0)
        self.assertAlmostEqual(p["siscomex_planilha_brl"], 214.5, places=1)
        self.assertAlmostEqual(p["afrmm_pct_planilha"], 25.0, places=0)

    def test_motor_com_inputs_planilha_e_quebra(self):
        out = plus.calcular_desde_planilha_plus(PLANILHA)
        self.assertTrue(out["ok"])
        motor = out["motor"]
        self.assertTrue(motor["ok"])
        self.assertIn("quebra_outras_despesas", motor)
        self.assertGreater(motor["outras_despesas_brl"], 0)
        self.assertAlmostEqual(motor["frete_internacional_usd"], 250.0, places=1)
        self.assertAlmostEqual(motor["cif_brl"], 23687.5, places=1)

    def test_deltas_afrmm_e_siscomex_documentados(self):
        out = plus.calcular_desde_planilha_plus(PLANILHA)
        d = out["deltas"]
        # Planilha 2019: AFRMM 25%; motor: 8% (Lei 14.301/2022)
        self.assertAlmostEqual(d["afrmm_pct_planilha"], 25.0, places=0)
        self.assertAlmostEqual(d["afrmm_pct_motor"], 8.0, places=0)
        self.assertLess(d["afrmm_brl_motor"], d["afrmm_brl_planilha"])
        # Siscomex legado 214,50 vs regra vigente
        self.assertAlmostEqual(d["siscomex_brl_planilha"], 214.5, places=1)
        vigente = taxa_siscomex_brl(adicoes=1)
        self.assertAlmostEqual(d["siscomex_brl_motor"], vigente, places=2)
        self.assertNotAlmostEqual(d["siscomex_brl_motor"], 214.5, places=1)
        self.assertIn("delta_total_brl", d)

    def test_outras_despesas_aumentam_custo(self):
        base = cl.calcular_custo_landed(
            10.0,
            cambio_usd_brl=5.0,
            quantidade=10,
            modo_frete="maritimo",
        )
        com = cl.calcular_custo_landed(
            10.0,
            cambio_usd_brl=5.0,
            quantidade=10,
            modo_frete="maritimo",
            outras_despesas_brl={"armazenagem_zp": 500.0, "capatazias": 100.0},
        )
        self.assertTrue(base["ok"] and com["ok"])
        self.assertGreater(com["custo_total_brl"], base["custo_total_brl"])
        self.assertEqual(com["quebra_outras_despesas"]["armazenagem_zp"], 500.0)
        self.assertAlmostEqual(com["outras_despesas_brl"], 600.0, places=1)

    def test_frete_absoluto_override(self):
        out = cl.calcular_custo_landed(
            100.0,
            cambio_usd_brl=5.0,
            quantidade=1,
            frete_internacional_usd=50.0,
            seguro_brl=0.0,
            seguro_pct=0.0,
        )
        self.assertTrue(out["ok"])
        self.assertAlmostEqual(out["frete_internacional_usd"], 50.0, places=1)
        self.assertAlmostEqual(out["frete_internacional_brl"], 250.0, places=1)

    def test_catalogo_despesas_padrao(self):
        padrao = plus.carregar_despesas_padrao()
        self.assertIn("armazenagem_zp", padrao)
        self.assertGreater(padrao["armazenagem_zp"], 0)

    def test_caminho_default(self):
        p = plus.caminho_planilha_plus()
        self.assertIsInstance(p, Path)
        self.assertTrue(str(p).endswith("importacao_simula_plus_brasil.xlsx"))


if __name__ == "__main__":
    unittest.main()
