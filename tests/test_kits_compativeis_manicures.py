"""tests/test_kits_compativeis_manicures.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from agentes.esmaltes.agente_montar_kits_impala import montar_mensagem_telegram
from integracoes.esmaltes import kits_compativeis_manicures as km


def _kit_mimo():
    return {
        "sku": "IMP-MIMO-003",
        "nome": "Kit 3 Esmaltes Impala Mimo + Carmed Manicure",
        "preco": 44.9,
        "custo_total": 28.13,
        "cores": [{"nome": "Admire"}, {"nome": "Sutileza"}, {"nome": "Amor Profundo"}],
        "canais": {"mercadolivre": {"preco": 44.9, "taxa_canal_pct": 18.0}},
    }


def _kit_perl(**kwargs):
    base = {
        "sku": "IMP-PERL-004",
        "nome": "Kit 4 Esmaltes Impala Perolado",
        "preco": 39.9,
        "custo_total": 26.23,
        "vd_dia_ml_ref": 15,
        "score_alavancagem": 642,
        "margem_trabalho_pct": 42.8,
        "cores": [
            {"nome": "Sonho"},
            {"nome": "Polar"},
            {"nome": "Lua"},
            {"nome": "Dengo"},
        ],
        "canais": {"mercadolivre": {"preco": 39.9, "taxa_canal_pct": 18.0}},
    }
    base.update(kwargs)
    return base


def _kit_sort10():
    return {
        "sku": "IMP-SORT-010",
        "nome": "Kit 10 Atacado",
        "preco": 48.0,
        "custo_total": 53.15,
        "vd_dia_ml_ref": 15,
        "score_alavancagem": 177,
        "margem_trabalho_pct": 11.8,
        "cores": [{"nome": "Vinho"}, {"nome": "Zaz"}, {"nome": "Nude"}],
        "canais": {"mercadolivre": {"preco": 48.0, "taxa_canal_pct": 18.0}},
    }


class TestEconomiaIndice(unittest.TestCase):
    def test_economia_kit_vs_avulso(self):
        eco = km.economia_kit_vs_unitario(4, 39.9, 12.0)
        self.assertEqual(eco["custo_n_avulsos"], 48.0)
        self.assertAlmostEqual(eco["economia_brl"], 8.1, places=1)
        self.assertAlmostEqual(eco["economia_pct"], 16.9, places=1)
        self.assertAlmostEqual(eco["preco_por_unidade"], 9.97, places=2)

    def test_indice_compra_impala(self):
        indice = km.indice_compra_impala(
            _kit_perl(),
            [{"quantidade_vendida": 20}],
        )
        self.assertEqual(indice, 298)

    def test_perfil_manicure(self):
        self.assertEqual(km.perfil_manicure(3), "manicure_autonoma")
        self.assertEqual(km.perfil_manicure(5), "salao_giro")
        self.assertEqual(km.perfil_manicure(10), "salao_estoque")


class TestOfertaImpala(unittest.TestCase):
    def test_perl_tem_condicao_e_padrao(self):
        row = km.avaliar_oferta_impala(_kit_perl(), anuncios=[], preco_unitario_ref=12.0)
        self.assertIsNotNone(row)
        self.assertTrue(row["padrao_impala"])
        self.assertTrue(row["condicao_ok"])
        self.assertEqual(row["perfil_manicure"], "manicure_autonoma")
        self.assertEqual(row["kit_tag"], "kit:perl004")
        self.assertNotIn("sku:", row["kit_tag"])

    def test_sort10_sem_condicao_por_margem(self):
        row = km.avaliar_oferta_impala(_kit_sort10(), anuncios=[], preco_unitario_ref=12.0)
        self.assertIsNotNone(row)
        self.assertFalse(row["condicao_ok"])
        self.assertLess(float(row["margem_pct"]), 15.0)

    def test_mimo_tem_condicao_por_extra_carmed(self):
        row = km.avaliar_oferta_impala(_kit_mimo(), anuncios=[], preco_unitario_ref=12.0)
        self.assertIsNotNone(row)
        self.assertTrue(row["condicao_ok"])
        self.assertEqual(row["motivo_condicao"], "entrada_carmed")
        self.assertLess(float(row["economia"]["economia_pct"]), 0)

    def test_sku_nao_impala_ignorado(self):
        self.assertIsNone(
            km.avaliar_oferta_impala({"sku": "MP-X-003", "preco": 10, "cores": [{"nome": "A"}]})
        )

    def test_impala_ranqueia_acima_anita_mesmo_tamanho(self):
        anuncios = [
            {
                "titulo": "Kit 4 Esmaltes Anita Nude",
                "marca": "Anita",
                "qtd_kit": 4,
                "preco": 42.0,
                "quantidade_vendida": 200,
                "cores_detectadas": ["nude"],
            },
            {
                "titulo": "Kit 4 Esmaltes Impala Sonho Polar",
                "marca": "Impala",
                "qtd_kit": 4,
                "preco": 40.0,
                "quantidade_vendida": 50,
                "cores_detectadas": ["sonho", "polar"],
            },
        ]
        ranked = km.ranquear_compativeis_ml(_kit_perl(), anuncios)
        self.assertTrue(ranked)
        self.assertTrue(ranked[0]["impala"])
        self.assertGreater(ranked[0]["overlap_cores"], 0)
        self.assertGreater(ranked[0]["score_compat"], ranked[1]["score_compat"])

    @patch.object(km, "incrementar")
    @patch.object(km, "gauge")
    def test_montar_ranking_prioriza_condicao(self, _g, _i):
        anita = {
            "titulo": "Kit 4 Anita Nude",
            "marca": "Anita",
            "qtd_kit": 4,
            "preco": 45.0,
            "quantidade_vendida": 120,
            "cores_detectadas": ["nude"],
        }
        out = km.montar_ofertas_manicure(
            produtos=[_kit_perl(), _kit_sort10()],
            anuncios=[anita],
            piso_margem_pct=15.0,
        )
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["condicao_n"], 1)
        self.assertEqual(out["ofertas"][0]["sku"], "IMP-PERL-004")
        self.assertTrue(out["ofertas_condicao"][0]["condicao_ok"])

    @patch.object(km, "incrementar")
    @patch.object(km, "gauge")
    def test_piso_avulso_ignora_dump_ml(self, _g, _i):
        anuncios = [
            {
                "titulo": "Esmalte Impala unitario",
                "tipo_anuncio": "unitario",
                "qtd_kit": 1,
                "preco": 9.0,
            }
        ]
        out = km.montar_ofertas_manicure(produtos=[_kit_perl()], anuncios=anuncios)
        self.assertGreaterEqual(out["preco_unitario_ref"], 12.0)
        self.assertLessEqual(out["preco_unitario_ml"], 9.0)
        self.assertTrue(out["ofertas"][0]["condicao_ok"])

    def test_secao_telegram(self):
        linhas = km.formatar_secao_manicure(
            [
                {
                    "sku": "IMP-PERL-004",
                    "qtd_kit": 4,
                    "perfil_manicure": "manicure_autonoma",
                    "condicao_ok": True,
                    "indice_compra": 278,
                    "preco": 39.9,
                    "economia": {"economia_pct": 16.9, "economia_brl": 8.1},
                    "compativeis_ml": [{"titulo": "Kit 4 Impala", "marca": "Impala", "quantidade_vendida": 50}],
                }
            ]
        )
        blob = "\n".join(linhas)
        self.assertIn("IMP-PERL-004", blob)
        self.assertIn("economia", blob.lower())


class TestAgenteMontarKitsSecao(unittest.TestCase):
    def test_mensagem_inclui_ofertas_manicure(self):
        msg = montar_mensagem_telegram(
            {
                "total_cores_planilha": 2,
                "cores_com_demanda": 1,
                "total_kits_ml": 1,
                "top_cores": [],
                "ofertas_manicure": {
                    "ofertas_condicao": [
                        {
                            "sku": "IMP-PERL-004",
                            "qtd_kit": 4,
                            "perfil_manicure": "manicure_autonoma",
                            "condicao_ok": True,
                            "indice_compra": 278,
                            "preco": 39.9,
                            "economia": {"economia_pct": 16.9, "economia_brl": 8.1},
                        }
                    ]
                },
            },
            {"preco_medio": 42.0},
        )
        self.assertIn("IMP-PERL-004", msg)
        self.assertIn("manicures", msg.lower())


if __name__ == "__main__":
    unittest.main()
