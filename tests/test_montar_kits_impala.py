"""tests/test_montar_kits_impala.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import cruzamento_kits_planilha as cruz
from integracoes.esmaltes import planilha_impala as pl


class TestPlanilhaImpala(unittest.TestCase):
    def test_extrair_nome_cor_cremoso(self):
        self.assertEqual(
            pl.extrair_nome_cor("ESMALTE IMPALA A COR DA MODA CREMOSO VINHO COMERCIAL"),
            "Vinho",
        )

    def test_extrair_nome_cor_composta(self):
        self.assertIn(
            "Maria",
            pl.extrair_nome_cor("ESMALTE IMPALA A COR DA MODA CREMOSO MARIA CEREJA COMERCIAL"),
        )

    def test_extrair_suave_cobertura(self):
        self.assertIn(
            "Cigana",
            pl.extrair_nome_cor("ESMALTE IMPALA A COR DA MODA SUAVE COBERTURA CIGANA COMERCIAL"),
        )

    def test_tokens_cor(self):
        toks = pl.tokens_cor("Maria Cereja", "ESMALTE IMPALA CREMOSO MARIA CEREJA")
        self.assertTrue(any("maria" in t for t in toks))

    def test_carregar_planilha_real_se_existir(self):
        prods = pl.carregar_produtos_planilha()
        if not pl.PLANILHA_DEFAULT.is_file():
            self.skipTest("planilha ausente")
        self.assertGreater(len(prods), 100)
        impala = pl.cores_impala_disponiveis(prods)
        self.assertGreater(len(impala), 50)
        kits = pl.carregar_kits_planilha()
        self.assertGreaterEqual(len(kits), 10)


class TestCruzamentoKits(unittest.TestCase):
    def setUp(self):
        self.produtos = [
            {
                "sku": "1",
                "ean": "1",
                "descricao": "ESMALTE IMPALA CREMOSO BAILARINA COMERCIAL",
                "marca": "Impala",
                "tipo": "Esmalte",
                "nome_cor": "Bailarina",
                "tokens": ["bailarina"],
                "eh_esmalte": True,
                "eh_impala": True,
                "eh_cor_moda": True,
            },
            {
                "sku": "2",
                "ean": "2",
                "descricao": "ESMALTE IMPALA CREMOSO VINHO COMERCIAL",
                "marca": "Impala",
                "tipo": "Esmalte",
                "nome_cor": "Vinho",
                "tokens": ["vinho"],
                "eh_esmalte": True,
                "eh_impala": True,
                "eh_cor_moda": True,
            },
            {
                "sku": "3",
                "ean": "3",
                "descricao": "ESMALTE IMPALA CREMOSO ZAZ COMERCIAL",
                "marca": "Impala",
                "tipo": "Esmalte",
                "nome_cor": "Zaz",
                "tokens": ["zaz"],
                "eh_esmalte": True,
                "eh_impala": True,
                "eh_cor_moda": True,
            },
        ]
        self.kits_ml = [
            {
                "item_id": "MLB1",
                "titulo": "Kit 5 Esmaltes Impala Bailarina Nude Rosa Manicure",
                "quantidade_vendida": 200,
                "preco": 48.9,
                "qtd_kit": 5,
            },
            {
                "item_id": "MLB2",
                "titulo": "Kit 3 Esmaltes Vinho Marsala Atacado",
                "quantidade_vendida": 80,
                "preco": 35.0,
                "qtd_kit": 3,
            },
        ]

    def test_ranquear_cores(self):
        ranked = cruz.ranquear_cores_por_demanda_ml(self.kits_ml, self.produtos, top_kits=10)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["nome_cor"], "Bailarina")
        self.assertGreater(float(ranked[0]["score_demanda"]), 0)

    def test_sugerir_kits(self):
        ranked = cruz.ranquear_cores_por_demanda_ml(self.kits_ml, self.produtos)
        sug = cruz.sugerir_kits_por_tamanho(ranked, tamanhos=(2, 3))
        self.assertTrue(sug)
        self.assertGreaterEqual(sug[0]["qtd"], 2)

    def test_avaliar_kits_cadastrados(self):
        kits_p = [
            {
                "ordem": 1,
                "nome": "Kit 5 Esmaltes Bailarina",
                "qtd": 5,
                "tokens": ["bailarina", "esmaltes", "kit"],
            }
        ]
        out = cruz.avaliar_kits_cadastrados(kits_p, self.kits_ml)
        self.assertIn(out[0]["demanda"], ("media", "alta"))
        self.assertGreaterEqual(out[0]["hits_ml"], 1)

    def test_cruzar_pipeline(self):
        with patch.object(cruz, "cores_impala_disponiveis", return_value=self.produtos):
            out = cruz.cruzar_planilha_com_mercado(
                self.kits_ml,
                produtos=self.produtos,
                kits_cadastrados=[
                    {"ordem": 1, "nome": "Kit Bailarina", "qtd": 5, "tokens": ["bailarina"]}
                ],
            )
        self.assertTrue(out["ok"])
        self.assertGreater(out["cores_com_demanda"], 0)
        self.assertTrue(out["kits_sugeridos"])


if __name__ == "__main__":
    unittest.main()
