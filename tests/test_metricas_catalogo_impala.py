"""tests/test_metricas_catalogo_impala.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import metricas_catalogo_impala as m


class TestMetricasCatalogoImpala(unittest.TestCase):
    def setUp(self):
        self.produtos = [
            {
                "sku": "IMP-PERL-004",
                "prioridade": "P0",
                "score_alavancagem": 642,
                "vd_dia_ml_ref": 15,
                "margem_trabalho_pct": 42.8,
                "preco_ml_mercado": 42.0,
                "lucro_ref_ml": 17.96,
                "custo_total": 20.23,
                "fase_atual": 1,
                "preco": 39.9,
                "estoque_total": 0,
                "canais": {
                    "mercadolivre": {
                        "item_id": "MLB_PREENCHER",
                        "preco": 39.9,
                        "estoque": 0,
                        "taxa_canal_pct": 18.0,
                        "preco_concorrente": 42.0,
                    }
                },
            },
            {
                "sku": "IMP-VR-015",
                "prioridade": "P0",
                "score_alavancagem": 483,
                "vd_dia_ml_ref": 30,
                "margem_trabalho_pct": 16.1,
                "preco_ml_mercado": 72.9,
                "lucro_ref_ml": 11.73,
                "custo_total": 60.9,
                "fase_atual": 1,
                "preco": 69.9,
                "estoque_total": 5,
                "canais": {
                    "mercadolivre": {
                        "item_id": "MLB123456789",
                        "preco": 69.9,
                        "estoque": 5,
                        "taxa_canal_pct": 18.0,
                    }
                },
            },
            {
                "sku": "IMP-NUDE-010",
                "prioridade": "P1",
                "score_alavancagem": 86,
                "vd_dia_ml_ref": 5,
                "margem_trabalho_pct": 17.2,
                "preco_ml_mercado": 52.0,
                "custo_total": 43.65,
                "preco": 49.9,
                "estoque_total": 0,
                "canais": {
                    "mercadolivre": {
                        "item_id": "MLB_PREENCHER",
                        "preco": 49.9,
                        "estoque": 0,
                        "taxa_canal_pct": 18.0,
                    }
                },
            },
        ]
        self.guerra = [
            {"sku": "IMP-PERL-004", "papel": "entrada"},
            {"sku": "IMP-VR-015", "papel": "giro"},
        ]

    def test_kit_tag(self):
        self.assertEqual(m.kit_tag("IMP-PERL-004"), "kit:perl004")
        self.assertEqual(m.kit_tag("BUNDLE-777-5ESM"), "kit:b7775esm")

    def test_snapshot_agregados(self):
        snap = m.montar_snapshot_catalogo(
            produtos=self.produtos, guerra=self.guerra
        )
        self.assertEqual(snap["kits_total"], 3)
        self.assertEqual(snap["kits_p0"], 2)
        self.assertEqual(snap["kits_p1"], 1)
        self.assertEqual(snap["sem_mlb"], 2)
        self.assertEqual(snap["guerra_sem_mlb"], 1)
        self.assertEqual(snap["guerra_estoque_zero"], 1)
        by = {k["sku"]: k for k in snap["kits"]}
        self.assertEqual(by["IMP-PERL-004"]["papel"], "entrada")
        self.assertFalse(by["IMP-PERL-004"]["mlb_ok"])
        self.assertTrue(by["IMP-VR-015"]["mlb_ok"])
        self.assertEqual(by["IMP-NUDE-010"]["papel"], "catalogo")
        self.assertIsNotNone(by["IMP-PERL-004"]["margem_real_pct"])
        self.assertGreater(by["IMP-PERL-004"]["gap_mercado_pct"], 0)

    @patch("integracoes.esmaltes.metricas_catalogo_impala.incrementar")
    @patch("integracoes.esmaltes.metricas_catalogo_impala.gauge")
    def test_emitir_chama_gauges(self, mock_gauge, mock_inc):
        out = m.emitir_metricas_catalogo_impala(
            produtos=self.produtos, guerra=self.guerra
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["kits_emitidos"], 3)
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("catalogo.kits_total", nomes)
        self.assertIn("catalogo.guerra_sem_mlb", nomes)
        self.assertIn("catalogo.margem_trabalho_pct", nomes)
        self.assertIn("catalogo.margem_real_pct", nomes)
        # nenhuma tag sku:
        for c in mock_gauge.call_args_list:
            tags = (c.kwargs.get("tags") or (c.args[2] if len(c.args) > 2 else None) or [])
            if tags is None:
                tags = []
            self.assertFalse(any(str(t).startswith("sku:") for t in tags))
        mock_inc.assert_any_call("catalogo.heartbeat")


if __name__ == "__main__":
    unittest.main()
