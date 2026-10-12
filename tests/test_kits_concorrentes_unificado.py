"""tests/test_kits_concorrentes_unificado.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import kits_concorrentes_unificado as ku


class TestKitsConcorrentesUnificado(unittest.TestCase):
    def test_montar_junta_radar_e_petg(self):
        blobs = {
            "radar": {
                "ok": True,
                "timestamp": "2026-08-16T12:00:00+00:00",
                "cache_stale": True,
                "n_anuncios": 2,
                "n_comparaveis": 0,
                "extras": {"francesinha": 8, "tratamento": 5},
                "rivais": [
                    {
                        "item_id": "MLB1",
                        "titulo": "Kit 3 Francesinha",
                        "preco": 22.5,
                        "qtd_kit": 3,
                        "extras": ["francesinha"],
                    }
                ],
            },
            "marca_kit": {
                "timestamp": "2026-08-16T12:00:00+00:00",
                "ranking": [
                    {
                        "marca": "Impala",
                        "qtd_kit": 5,
                        "anuncios": 1,
                        "preco_medio": 42.0,
                        "preco_por_unidade": 8.4,
                        "vendidos": 200,
                    }
                ],
            },
            "nossos": {
                "ok": True,
                "ofertas": [
                    {
                        "sku": "IMP-MIMO-003",
                        "qtd_kit": 3,
                        "preco": 44.9,
                        "margem_pct": 19.35,
                        "condicao_ok": True,
                        "economia": {"preco_por_unidade": 14.97},
                        "compativeis_ml": [],
                    }
                ],
            },
            "anita": {
                "consolidado_impala": {
                    "share_impala_global_pct": 62.5,
                    "unidades_vendidas_impala": 200,
                    "unidades_vendidas_anita": 120,
                },
                "resultados": [{"nome": "Kit 5", "total_anuncios": 2, "menor_preco_impala": 42.0}],
            },
            "petg": {
                "consolidado": {
                    "total_anuncios_ativos": 42,
                    "produtos": [
                        {"titulo": "PETG Preto 1kg", "preco": 99.0, "item_id": "A"},
                        {
                            "titulo": "Kit 2x Petg Preto",
                            "preco": 209.9,
                            "item_id": "B",
                            "seller_id": "1",
                            "cor": "Preto",
                        },
                    ],
                }
            },
            "mercado": {},
            "anuncio": {},
            "kits_monitor": {},
        }
        snap = ku.montar_unificado(blobs=blobs)
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["fontes_total"], 8)
        self.assertGreaterEqual(snap["fontes_presentes"], 5)
        esm = snap["esmaltes"]
        self.assertEqual(esm["n_rivais"], 2)
        self.assertEqual(esm["extras"]["francesinha"], 8)
        self.assertEqual(esm["rivais"][0]["qtd_kit"], 3)
        self.assertEqual(esm["nossos"][0]["sku"], "IMP-MIMO-003")
        self.assertEqual(esm["marca_kit"][0]["marca"], "Impala")
        self.assertEqual(snap["filamentos"]["kits_no_titulo"], 1)
        self.assertEqual(snap["onde"]["unico"], "logs/kits_concorrentes_unificado_ultima.json")

    def test_fontes_vazias_ainda_ok(self):
        snap = ku.montar_unificado(blobs={fid: {} for fid, _, _ in ku.FONTES})
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["esmaltes"]["n_rivais"], 0)
        self.assertEqual(snap["filamentos"]["kits_no_titulo"], 0)

    @patch("integracoes.esmaltes.kits_concorrentes_unificado.incrementar")
    @patch("integracoes.esmaltes.kits_concorrentes_unificado.gauge")
    def test_emitir_gauges(self, mock_g, mock_i):
        snap = ku.montar_unificado(
            blobs={
                "radar": {"n_anuncios": 3, "extras": {"francesinha": 2}, "rivais": []},
                **{fid: {} for fid, _, _ in ku.FONTES if fid != "radar"},
            }
        )
        ku.emitir_metricas(snap)
        nomes = [c.args[0] for c in mock_g.call_args_list]
        self.assertIn("kits.unificado.rivais_n", nomes)
        self.assertIn("kits.unificado.francesinha", nomes)
        mock_i.assert_not_called()

    @patch("integracoes.esmaltes.kits_concorrentes_unificado.escrever_json_atomico")
    @patch("integracoes.esmaltes.kits_concorrentes_unificado.incrementar")
    @patch("integracoes.esmaltes.kits_concorrentes_unificado.gauge")
    def test_processar_com_blobs_nao_grava(self, _g, mock_i, mock_w):
        out = ku.processar(blobs={fid: {} for fid, _, _ in ku.FONTES}, persistir=True)
        self.assertTrue(out["ok"])
        mock_w.assert_not_called()
        mock_i.assert_any_call("kits.unificado.ok")


if __name__ == "__main__":
    unittest.main()
