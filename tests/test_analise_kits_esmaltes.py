"""
tests/test_analise_kits_esmaltes.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import analise_kits_esmaltes as ake


class AnaliseKitsEsmaltesTests(unittest.TestCase):
    def test_processar_termo_filtra_somente_kits(self):
        segmento = {"id": "kit5", "nome": "Kit 5", "termo_busca": "kit 5 esmaltes"}
        anuncios = [
            {"titulo": "Kit 5 esmaltes Impala bailarina", "item_id": "MLB1", "preco": 48.0, "quantidade_vendida": 120},
            {"titulo": "Esmalte Anita unitário vermelho", "item_id": "MLB2", "preco": 8.0, "quantidade_vendida": 50},
        ]
        out = ake.processar_termo(segmento, anuncios)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_bruto"], 2)
        self.assertEqual(out["total_kits"], 1)
        self.assertEqual(out["kits"][0]["item_id"], "MLB1")

    def test_consolidar_varredura_deduplica_e_rankeia(self):
        resultados = [
            {
                "ok": True,
                "kits": [
                    {
                        "item_id": "MLB1",
                        "titulo": "Kit 10 Impala atacado",
                        "marca": "Impala",
                        "preco": 69.0,
                        "quantidade_vendida": 200,
                        "qtd_kit": 10,
                        "tipo_anuncio": "kit",
                    },
                    {
                        "item_id": "MLB2",
                        "titulo": "Kit 5 Anita nude",
                        "marca": "Anita",
                        "preco": 45.0,
                        "quantidade_vendida": 80,
                        "qtd_kit": 5,
                        "tipo_anuncio": "kit",
                    },
                ],
            },
            {
                "ok": True,
                "kits": [
                    {
                        "item_id": "MLB1",
                        "titulo": "Kit 10 Impala atacado",
                        "marca": "Impala",
                        "preco": 69.0,
                        "quantidade_vendida": 250,
                        "qtd_kit": 10,
                        "tipo_anuncio": "kit",
                    },
                ],
            },
        ]
        c = ake.consolidar_varredura(resultados)
        self.assertEqual(c["total_kits_unicos"], 2)
        self.assertEqual(c["total_vendas"], 330)
        self.assertTrue(c["vendas_proxy_confiavel"])
        self.assertEqual(c["ranking_marcas"][0]["marca"], "Impala")
        self.assertEqual(c["top_vendas"][0]["item_id"], "MLB1")
        self.assertEqual(len(c["kits_unicos"]), 2)

    def test_fmt_vendas_proxy_nd_quando_zero(self):
        self.assertEqual(ake.fmt_vendas_proxy(0), "n/d")
        self.assertEqual(ake.fmt_vendas_proxy(None), "n/d")
        self.assertEqual(ake.fmt_vendas_proxy(12), "12 vendas")

    def test_deltas_preco_itens(self):
        ant = {"MLB1": {"preco": 50.0, "titulo": "Kit A"}}
        agora = {"MLB1": {"preco": 40.0, "titulo": "Kit A"}, "MLB2": {"preco": 30.0, "titulo": "Kit B"}}
        deltas = ake.deltas_preco_itens(agora, ant, variacao_alerta_pct=5.0)
        self.assertTrue(any("caiu" in d for d in deltas))
        self.assertTrue(any("novos" in d for d in deltas))

    @patch("integracoes.ml.analise_anuncio_concorrente.enriquecer_lista", side_effect=lambda xs, **kw: xs)
    @patch("integracoes.ml.ml_client.buscar_item_publico")
    def test_enriquecer_top_atualiza_sold(self, mock_pub, _enrich):
        mock_pub.return_value = {
            "item_id": "MLB1",
            "preco": 70.0,
            "sold_quantity": 400,
            "status": "active",
            "seller_id": "99",
        }
        base = ake.consolidar_varredura(
            [
                {
                    "ok": True,
                    "kits": [
                        {
                            "item_id": "MLB1",
                            "titulo": "Kit 10 Impala",
                            "marca": "Impala",
                            "preco": 69.0,
                            "quantidade_vendida": 0,
                            "qtd_kit": 10,
                            "tipo_anuncio": "kit",
                        }
                    ],
                }
            ]
        )
        self.assertFalse(base["vendas_proxy_confiavel"])
        out = ake.enriquecer_top_kits(base, limite=3)
        self.assertEqual(out["total_vendas"], 400)
        self.assertTrue(out["vendas_proxy_confiavel"])
        self.assertEqual(out["enriquecidos"], 1)


if __name__ == "__main__":
    unittest.main()
