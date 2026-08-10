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

    def test_dias_desde(self):
        self.assertIsNone(aa.dias_desde(""))
        self.assertIsNone(aa.dias_desde("lixo"))
        d = aa.dias_desde("2024-01-01T00:00:00Z")
        self.assertIsNotNone(d)
        self.assertGreaterEqual(d, 0)

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

    def test_montar_mensagem_metricas(self):
        msg = aa.montar_mensagem_metricas(
            {
                "termo": "kit impala",
                "total": 1,
                "taxa_estimada_pct": 13,
                "anuncios": [
                    {
                        "titulo": "Kit Bailarina",
                        "item_id": "MLB1",
                        "metricas": {
                            "preco": 30.99,
                            "vendas": 10,
                            "vendas_por_dia": 0.5,
                            "avaliacoes": 5,
                            "nota": 4.8,
                            "receita_liquida_un": 26.96,
                            "visitas_disponivel": False,
                        },
                    }
                ],
            }
        )
        self.assertIn("kit impala", msg)
        self.assertIn("Bailarina", msg)


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

    @patch.object(
        aa,
        "enriquecer_anuncio",
        side_effect=lambda a, **kw: {**a, "metricas": {"preco": a.get("preco")}},
    )
    def test_enriquecer_lista_limite(self, mock_enr):
        rows = [{"item_id": f"MLB{i}", "preco": float(i)} for i in range(5)]
        out = aa.enriquecer_lista(rows, limite=2)
        self.assertEqual(len(out), 5)
        self.assertEqual(mock_enr.call_count, 5)
        self.assertTrue(mock_enr.call_args_list[0].kwargs.get("buscar_reviews"))
        self.assertFalse(mock_enr.call_args_list[2].kwargs.get("buscar_reviews"))

    @patch.object(aa.ml_client, "buscar_concorrentes_por_termo")
    @patch.object(aa, "enriquecer_lista")
    def test_analisar_por_termo(self, mock_enr, mock_busca):
        mock_busca.return_value = [{"item_id": "MLB1", "preco": 10}]
        mock_enr.return_value = [{"item_id": "MLB1", "preco": 10, "metricas": {"preco": 10}}]
        out = aa.analisar_por_termo("kit impala", limite=3)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total"], 1)
        mock_busca.assert_called_once()

    def test_analisar_por_termo_vazio(self):
        out = aa.analisar_por_termo("  ")
        self.assertFalse(out["ok"])


class VisitasPropriasTests(unittest.TestCase):
    @patch.object(aa, "ML_SELLER_ID", "111")
    @patch.object(aa.ml_client, "_enabled", return_value=True)
    @patch.object(aa.ml_client, "buscar_visitas_item")
    def test_terceiro_com_visitas(self, mock_vis, _en):
        mock_vis.return_value = {
            "ok": True,
            "disponivel": True,
            "visitas_7d": 58,
            "visitas_30d": 200,
        }
        out = aa.buscar_visitas_se_proprio("MLB9", "999")
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("disponivel"))
        self.assertEqual(out.get("visitas_7d"), 58)
        self.assertFalse(out.get("proprio"))

    @patch.object(aa, "ML_SELLER_ID", "111")
    @patch.object(aa.ml_client, "_enabled", return_value=True)
    @patch.object(aa.ml_client, "buscar_visitas_item")
    def test_terceiro_visitas_indisponivel(self, mock_vis, _en):
        mock_vis.return_value = {"ok": False, "disponivel": False, "motivo": "403"}
        out = aa.buscar_visitas_se_proprio("MLB9", "999")
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("disponivel"))
        self.assertIsNone(out.get("visitas_7d"))

    @patch.object(aa, "request")
    def test_buscar_reviews_ok(self, mock_req):
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {
            "paging": {"total": 12},
            "rating_average": 4.5,
            "stars": 5,
            "rating_levels": {},
        }
        with patch.object(aa.ml_client, "_enabled", return_value=False):
            out = aa.buscar_reviews_item("MLB1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["avaliacoes"], 12)
        self.assertEqual(out["nota"], 4.5)

    @patch.object(aa.ml_client, "_enabled", return_value=True)
    @patch.object(aa.ml_client, "_request_ml")
    def test_buscar_meta_catalogo(self, mock_req, _en):
        mock_req.return_value.status_code = 200
        mock_req.return_value.json.return_value = {
            "name": "Kit X",
            "date_created": "2024-01-01T00:00:00Z",
            "status": "active",
            "domain_id": "MLB-X",
            "permalink": "",
        }
        out = aa.buscar_meta_catalogo("MLB41490081")
        self.assertTrue(out["ok"])
        self.assertEqual(out["nome"], "Kit X")


if __name__ == "__main__":
    unittest.main()
