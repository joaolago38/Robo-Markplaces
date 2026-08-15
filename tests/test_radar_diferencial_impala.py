"""tests/test_radar_diferencial_impala.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import radar_diferencial_impala as rd


class TestRadarDiferencial(unittest.TestCase):
    def test_francesinha_nao_e_comparavel_ao_mimo(self):
        a = {"titulo": "Kit 3 Esmaltes Francesinha Impala Cor BRANCOS", "preco": 22.3, "qtd_kit": 3}
        self.assertFalse(rd.comparavel_frente(a, "IMP-MIMO-003"))
        self.assertIn("francesinha", rd.extras_titulo(a["titulo"]))

    def test_carmed_mimo_e_comparavel(self):
        a = {"titulo": "Kit 3 Esmaltes Impala Mimo + Carmed Manicure", "preco": 44.9, "qtd_kit": 3}
        self.assertTrue(rd.comparavel_frente(a, "IMP-MIMO-003"))
        self.assertIn("carmed", rd.extras_titulo(a["titulo"]))

    def test_tratamento_nao_e_mimo(self):
        a = {"titulo": "Kit 3 Esmaltes Impala Tratamento Incolor", "qtd_kit": 3}
        self.assertFalse(rd.comparavel_frente(a, "IMP-MIMO-003"))
        self.assertIn("tratamento", rd.extras_titulo(a["titulo"]))

    def test_montar_separa_lixo_e_margem(self):
        anuncios = [
            {"item_id": "MLB1A", "titulo": "Kit 3 Esmaltes Francesinha Impala", "preco": 22.3, "qtd_kit": 3},
            {"item_id": "MLB1B", "titulo": "Kit 3 Impala Mimo Carmed", "preco": 46.0, "qtd_kit": 3},
        ]
        produtos = [
            {
                "sku": "IMP-MIMO-003",
                "nome": "Kit 3 Mimo + Carmed",
                "custo_total": 28.13,
                "preco": 44.9,
                "canais": {"mercadolivre": {"preco": 44.9, "titulo_anuncio": "Kit 3 Mimo + Carmed", "taxa_canal_pct": 18}},
            },
            {
                "sku": "IMP-PERL-004",
                "custo_total": 26.23,
                "preco": 39.9,
                "canais": {"mercadolivre": {"preco": 39.9, "taxa_canal_pct": 18}},
            },
            {
                "sku": "IMP-JUPAES-006",
                "custo_total": 41.42,
                "preco": 64.9,
                "canais": {"mercadolivre": {"preco": 64.9, "taxa_canal_pct": 18}},
            },
        ]
        with patch.object(rd, "carregar_skus_guerra", return_value=[
            {"sku": "IMP-MIMO-003", "papel": "entrada", "diferencial_obrigatorio": "carmed"},
            {"sku": "IMP-PERL-004", "papel": "preco", "diferencial_obrigatorio": "perolado"},
            {"sku": "IMP-JUPAES-006", "papel": "giro", "diferencial_obrigatorio": "ju paes"},
        ]):
            out = rd.montar_radar(anuncios, produtos=produtos)
        self.assertEqual(out["n_comparaveis"], 1)
        self.assertEqual(out["n_nao_comparaveis"], 1)
        mimo = next(m for m in out["margens"] if m["sku"] == "IMP-MIMO-003")
        self.assertGreaterEqual(mimo["margem_op_pct"], 19.0)
        self.assertTrue(mimo["acima_piso15"])
        self.assertIn("carmed", mimo["nossos_extras"])
        self.assertIn("francesinha", out["extras"])
        self.assertIn("datadoghq.com/dashboard/", rd.formatar_mensagem(out))
        self.assertIn("francesinha", out["extras"])
        self.assertEqual(out["extras"].get("carmed"), 1)
        self.assertEqual(out["extras"].get("brinde"), 0)
        self.assertEqual(out["mlb_frente"], 0)
        self.assertIn("Publicar MIMO", out["fazer"])
        self.assertEqual(out["fonte"], "amostra")
        self.assertEqual(out["condicoes"]["fase"], 0)
        self.assertIn("Fase guerra 0", rd.formatar_mensagem(out))

    def test_perl_perola_acentuada_e_comparavel(self):
        a = {"titulo": "Kit 4 Esmaltes Impala Pérola Sonho Lua", "preco": 39.9, "qtd_kit": 4}
        self.assertTrue(rd.comparavel_frente(a, "IMP-PERL-004"))

    def test_amostra_vazia_cai_no_cache(self):
        cache = [{"item_id": "MLB9C", "titulo": "Kit 3 Impala Mimo Carmed", "preco": 46.0, "qtd_kit": 3}]
        produtos = [{"sku": "IMP-MIMO-003", "custo_total": 28.13, "preco": 44.9, "estoque_total": 0}]
        with patch.object(rd, "_anuncios_do_cache", return_value=(cache, 12.0)):
            with patch.object(rd, "carregar_skus_guerra", return_value=[{"sku": "IMP-MIMO-003", "papel": "entrada"}]):
                out = rd.montar_radar([], produtos=produtos)
        self.assertEqual(out["fonte"], "cache_busca")
        self.assertEqual(out["n_comparaveis"], 1)
        self.assertFalse(out["cache_stale"])

    def test_cache_stale_flag(self):
        cache = [{"item_id": "MLB9C", "titulo": "Kit 3 francesinha Impala", "qtd_kit": 3}]
        with patch.object(rd, "_anuncios_do_cache", return_value=(cache, 80.0)):
            with patch.object(rd, "carregar_skus_guerra", return_value=[]):
                out = rd.montar_radar([], produtos=[])
        self.assertTrue(out["cache_stale"])
        self.assertEqual(out["cache_idade_h"], 80.0)
        self.assertFalse(out["mercado_confiavel"])
        self.assertFalse(out["amostra_viva"])

    @patch.object(rd, "incrementar")
    @patch.object(rd, "gauge")
    def test_cache_stale_datadog_emite_zero_de_mercado(self, mock_g, _inc):
        payload = {
            "n_comparaveis": 3,
            "n_nao_comparaveis": 17,
            "n_anuncios": 20,
            "extras": {"francesinha": 8, "carmed": 1},
            "cache_stale": True,
            "mercado_confiavel": False,
            "amostra_viva": False,
            "mlb_frente": 0,
            "estoque_frente": 0,
            "cache_idade_h": 862.0,
            "margens": [
                {
                    "sku": "IMP-MIMO-003",
                    "kit_tag": "kit:mimo003",
                    "papel": "entrada",
                    "margem_op_pct": 19.35,
                    "acima_piso15": True,
                    "rivais_comparaveis": 2,
                    "nossos_extras": ["carmed"],
                    "mlb_ok": False,
                }
            ],
        }
        rd.emitir_metricas_radar(payload)
        enviados = {(c.args[0], c.args[1] if len(c.args) > 1 else None) for c in mock_g.call_args_list}
        self.assertIn(("impala.guerra.rivais_comparaveis", 0.0), enviados)
        self.assertIn(("impala.guerra.rivais_nao_comparaveis", 0.0), enviados)
        self.assertIn(("impala.guerra.rivais_amostra", 0.0), enviados)
        self.assertIn(("impala.guerra.mercado_confiavel", 0.0), enviados)
        self.assertIn(("impala.guerra.mlb_frente", 0.0), enviados)
        carmed = [
            c for c in mock_g.call_args_list
            if c.args and c.args[0] == "impala.guerra.nosso_carmed"
        ]
        self.assertTrue(carmed)
        self.assertEqual(carmed[0].args[1], 0.0)
        extras = [
            c for c in mock_g.call_args_list
            if c.args and c.args[0] == "impala.guerra.extra_n"
        ]
        self.assertTrue(all(c.args[1] == 0.0 for c in extras))
        mop = [
            c for c in mock_g.call_args_list
            if c.args and c.args[0] == "impala.guerra.margem_op_pct"
        ]
        self.assertEqual(mop[0].args[1], 19.35)
        piso = [
            c for c in mock_g.call_args_list
            if c.args and c.args[0] == "impala.guerra.kits_acima_piso15"
        ]
        self.assertEqual(piso[0].args[1], 1.0)

    def test_estoque_zero_com_mlb_pede_estoque(self):
        produtos = [
            {
                "sku": "IMP-MIMO-003",
                "custo_total": 28.13,
                "preco": 44.9,
                "estoque_total": 0,
                "canais": {"mercadolivre": {"item_id": "MLB12345678", "preco": 44.9, "estoque": 0, "taxa_canal_pct": 18}},
            }
        ]
        with patch.object(rd, "carregar_skus_guerra", return_value=[{"sku": "IMP-MIMO-003"}]):
            out = rd.montar_radar(
                [{"item_id": "MLB1A", "titulo": "Kit 3 francesinha Impala", "qtd_kit": 3}],
                produtos=produtos,
            )
        self.assertEqual(out["mlb_frente"], 1)
        self.assertIn("estoque", out["fazer"].lower())
