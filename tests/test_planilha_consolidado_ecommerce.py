# -*- coding: utf-8 -*-
"""tests/test_planilha_consolidado_ecommerce.py"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import planilha_consolidado_ecommerce as pc


class TestHelpers(unittest.TestCase):
    def test_money_and_sku(self):
        self.assertAlmostEqual(pc._f("R$ 281.30"), 281.30)
        self.assertAlmostEqual(pc._f("R$ 10.48 (23%)"), 10.48)
        self.assertEqual(pc._pct_lucro_cell("R$ 10.48 (23%)"), 23.0)
        self.assertEqual(pc._sku_de("IMP-MIMO-003  Kit 3 Mimo"), "IMP-MIMO-003")
        self.assertEqual(pc._sku_de("CRZ-KIT-103"), "CRZ-KIT-103")

    def test_frete_faixas(self):
        faixas = [
            {"teto_g": 350, "frete_reais": 9},
            {"teto_g": 530, "frete_reais": 11},
            {"teto_g": 1000, "frete_reais": 14.5},
        ]
        self.assertEqual(pc.frete_para_peso_gramas(300, faixas), 9)
        self.assertEqual(pc.frete_para_peso_gramas(400, faixas), 11)
        self.assertEqual(pc.frete_para_peso_gramas(2000, faixas), 14.5)


@unittest.skipUnless(
    (Path(__file__).resolve().parents[1] / "planilhas_ecommerce" / "Consolidado_Impala_Cruzeiro.xlsx").is_file(),
    "planilha consolidado ausente",
)
class TestParseReal(unittest.TestCase):
    def test_parse_plano_e_resumo(self):
        planos = pc.parse_plano_validacao()
        self.assertGreaterEqual(len(planos), 5)
        self.assertTrue(all(p["invest_validacao_reais"] > 0 for p in planos))
        resumos = pc.parse_resumo_kits()
        self.assertGreaterEqual(len(resumos), 5)
        self.assertTrue(any(r["frete_estimado"] >= 9 for r in resumos))
        crz = pc.parse_kits_cruzeiro()
        self.assertGreaterEqual(len(crz), 3)
        self.assertTrue(all(k["sku"].startswith("CRZ-") for k in crz))

    @patch("integracoes.esmaltes.planilha_consolidado_ecommerce.gauge")
    @patch("integracoes.esmaltes.planilha_consolidado_ecommerce.incrementar")
    def test_sync_escreve_catalogos(self, mock_inc, mock_gauge):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # redireciona outputs para temp, mantém leitura da planilha real
            with patch.object(pc, "CAT_PLANO", tmp_path / "plano.json"), patch.object(
                pc, "CAT_CRUZEIRO", tmp_path / "crz.json"
            ), patch.object(pc, "CAT_OPORT", tmp_path / "oport.json"), patch.object(
                pc, "CAT_LIVIA", tmp_path / "livia.json"
            ), patch.object(pc, "CAT_FRETE", tmp_path / "frete.json"), patch.object(
                pc, "CAT_PRODUTOS", tmp_path / "produtos.json"
            ), patch.object(
                pc, "ROOT", tmp_path
            ):
                (tmp_path / "logs").mkdir(exist_ok=True)
                (tmp_path / "catalogo").mkdir(exist_ok=True)
                # produtos mínimos
                from core.atomic_io import escrever_json_atomico

                escrever_json_atomico(
                    tmp_path / "produtos.json",
                    [
                        {
                            "sku": "IMP-PERL-004",
                            "nome": "Kit teste",
                            "peso_gramas": 380,
                            "custo_total_sem_frete": 15.0,
                            "frete_estimado": 5.0,
                            "custo_total": 20.0,
                        }
                    ],
                )
                # ROOT/logs path used inside sync — patch escrever to use tmp logs via ROOT
                out = pc.sincronizar_planilhas_ecommerce(emitir_metricas=True)
                self.assertTrue(out.get("ok"), out)
                self.assertGreater(out.get("plano_validacao") or 0, 0)
                self.assertGreater(out.get("invest_total_reais") or 0, 0)
                self.assertTrue((tmp_path / "plano.json").is_file())
                self.assertTrue((tmp_path / "crz.json").is_file())
                mock_inc.assert_any_call("catalogo.planilha_ecommerce_sync")


if __name__ == "__main__":
    unittest.main()
