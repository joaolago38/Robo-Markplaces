"""
tests/test_analise_anuncio_concorrente.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.ml import analise_anuncio_concorrente as aa


class MetricasPurasTests(unittest.TestCase):
    def test_receita_estilo_lojahub(self):
        # 41.11 * (1 - 0.13) ≈ 35.77; 500 * 41.11 = 20555
        rec = aa.estimar_receitas(41.11, 500, taxa_pct=13.0)
        self.assertEqual(rec["receita_liquida_un"], 35.77)
        self.assertEqual(rec["receita_bruta_total"], 20555.0)
        self.assertEqual(rec["receita_liquida_total"], 17885.0)

    def test_vendas_por_dia(self):
        self.assertEqual(aa.estimar_vendas_por_dia(500, 22), 22.73)
        self.assertIsNone(aa.estimar_vendas_por_dia(0, 22))
        self.assertIsNone(aa.estimar_vendas_por_dia(10, None))

    def test_montar_metricas_com_catalogo(self):
        m = aa.montar_metricas(
            preco=30.99,
            vendas=100,
            catalog_date_created="2024-10-04T03:32:02Z",
            taxa_pct=13.0,
            reviews={"ok": True, "avaliacoes": 933, "nota": 4.9},
            visitas={"disponivel": False},
        )
        self.assertEqual(m["preco"], 30.99)
        self.assertEqual(m["vendas"], 100)
        self.assertIsNotNone(m["vendas_por_dia"])
        self.assertEqual(m["avaliacoes"], 933)
        self.assertEqual(m["nota"], 4.9)
        self.assertIsNone(m["visitas_7d"])
        self.assertAlmostEqual(m["receita_liquida_un"], 26.96)


class EnriquecerTests(unittest.TestCase):
    @patch.object(aa, "buscar_visitas_se_proprio", return_value={"disponivel": False})
    @patch.object(
        aa,
        "buscar_meta_catalogo",
        return_value={
            "ok": True,
            "date_created": "2024-10-04T03:32:02Z",
            "nome": "Kit Bailarina",
        },
    )
    @patch.object(
        aa,
        "buscar_reviews_item",
        return_value={"ok": True, "avaliacoes": 10, "nota": 4.8},
    )
    def test_enriquecer_anuncio(self, _r, _c, _v):
        out = aa.enriquecer_anuncio(
            {
                "item_id": "MLB1",
                "preco": 40.0,
                "quantidade_vendida": 22,
                "seller_id": "999",
                "catalog_product_id": "MLB41490081",
            },
            taxa_pct=13.0,
        )
        self.assertIn("metricas", out)
        self.assertEqual(out["nota"], 4.8)
        self.assertEqual(out["metricas"]["avaliacoes"], 10)
        self.assertEqual(out["metricas"]["vendas"], 22)

    @patch.object(aa.ml_client, "buscar_concorrentes_por_termo")
    @patch.object(aa, "enriquecer_lista")
    def test_analisar_por_termo(self, mock_enr, mock_busca):
        mock_busca.return_value = [{"item_id": "MLB1", "preco": 10}]
        mock_enr.return_value = [{"item_id": "MLB1", "preco": 10, "metricas": {"preco": 10}}]
        out = aa.analisar_por_termo("kit impala", limite=3)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total"], 1)
        mock_busca.assert_called_once()


class VisitasPropriasTests(unittest.TestCase):
    @patch.object(aa, "ML_SELLER_ID", "111")
    def test_terceiro_sem_visitas(self):
        out = aa.buscar_visitas_se_proprio("MLB9", "999")
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("disponivel"))
        self.assertIsNone(out.get("visitas_7d"))


if __name__ == "__main__":
    unittest.main()
