"""tests/test_analise_masterprint_petg.py"""
from __future__ import annotations

import unittest

from integracoes.filamentos import analise_filamentos_ml as af
from integracoes.filamentos import analise_masterprint_petg as mp
from integracoes.filamentos import custos_masterprint_petg as custos


class TestAnaliseMasterprintPetg(unittest.TestCase):
    def test_detecta_marca_masterprint(self):
        self.assertEqual(af.detectar_marca("Filamento PETG Masterprint Preto 1kg"), "Masterprint")

    def test_filtra_so_masterprint_petg(self):
        ok = mp.classificar_masterprint_petg(
            {
                "item_id": "MLB1",
                "titulo": "Filamento PETG Masterprint Preto 1kg 1.75mm",
                "preco": 89.9,
                "quantidade_vendida": 120,
            }
        )
        self.assertIsNotNone(ok)
        self.assertEqual(ok["receita_proxy"], round(89.9 * 120, 2))

        outro = mp.classificar_masterprint_petg(
            {
                "item_id": "MLB2",
                "titulo": "Filamento PETG eSUN Preto 1kg",
                "preco": 79.9,
                "quantidade_vendida": 200,
            }
        )
        self.assertIsNone(outro)

        pla = mp.classificar_masterprint_petg(
            {
                "item_id": "MLB3",
                "titulo": "Filamento PLA Masterprint Branco 1kg",
                "preco": 70.0,
                "quantidade_vendida": 50,
            }
        )
        self.assertIsNone(pla)

    def test_consolidar_rentaveis_e_ganho(self):
        resultados = [
            {
                "ok": True,
                "produtos": [
                    {
                        "item_id": "MLB1",
                        "titulo": "Filamento PETG Masterprint Preto 1kg",
                        "preco": 100.0,
                        "quantidade_vendida": 10,
                        "receita_proxy": 1000.0,
                        "marca": "Masterprint",
                        "material": "PETG",
                        "peso_kg": 1.0,
                    },
                    {
                        "item_id": "MLB2",
                        "titulo": "Filamento PETG Masterprint Branco 1kg",
                        "preco": 80.0,
                        "quantidade_vendida": 50,
                        "receita_proxy": 4000.0,
                        "marca": "Masterprint",
                        "material": "PETG",
                        "peso_kg": 1.0,
                    },
                ],
            }
        ]
        cons = mp.consolidar_masterprint_petg(resultados, produtos_anteriores=None, top_n=5)
        self.assertEqual(cons["total_anuncios_ativos"], 2)
        self.assertEqual(cons["custo_padrao_1kg_brl"], 45.96)
        # Com mesmo custo, mais vendas → maior lucro_proxy (MLB2)
        self.assertEqual(cons["mais_rentaveis"][0]["item_id"], "MLB2")
        self.assertIsNotNone(cons["mais_rentaveis"][0].get("margem_brl"))
        self.assertGreater(cons["mais_rentaveis"][0]["lucro_proxy"], 0)

        anteriores = [
            {
                "item_id": "MLB1",
                "quantidade_vendida": 5,
                "receita_proxy": 500.0,
            },
            {
                "item_id": "MLB2",
                "quantidade_vendida": 49,
                "receita_proxy": 3920.0,
            },
        ]
        cons2 = mp.consolidar_masterprint_petg(resultados, produtos_anteriores=anteriores, top_n=5)
        # MLB1 ganhou +5 vendas; MLB2 +1 — MLB1 deve liderar ganho
        self.assertEqual(cons2["maior_ganho"][0]["item_id"], "MLB1")
        self.assertEqual(cons2["maior_ganho"][0]["delta_vendas"], 5)


class TestCustosMasterprintPetg(unittest.TestCase):
    def setUp(self):
        custos.limpar_cache_custos()

    def test_casa_preto_1kg_padrao(self):
        m = custos.casar_custo_anuncio("Filamento PETG Masterprint Preto 1kg 1.75mm")
        self.assertIsNotNone(m)
        self.assertEqual(m["custo_unitario_brl"], 45.96)
        self.assertEqual(m["match"], "sku_tabela")
        self.assertEqual(m["sku"], "231020001")

    def test_casa_fosco_preto_mais_caro(self):
        m = custos.casar_custo_anuncio("Filamento PETG Masterprint Fosco Preto 1kg")
        self.assertIsNotNone(m)
        self.assertEqual(m["custo_unitario_brl"], 47.87)
        self.assertIn("Fosco", str(m.get("cor") or ""))

    def test_casa_carbono(self):
        m = custos.casar_custo_anuncio("Filamento PETG Masterprint Fibra de Carbono 1kg")
        self.assertIsNotNone(m)
        self.assertEqual(m["custo_unitario_brl"], 91.91)

    def test_margem_real_apos_taxa(self):
        # 100 * 0.84 - 45.96 = 38.04
        prod = custos.enriquecer_com_margem(
            {
                "titulo": "Filamento PETG Masterprint Preto 1kg",
                "preco": 100.0,
                "quantidade_vendida": 10,
                "peso_kg": 1.0,
            },
            taxa_ml_pct=16.0,
        )
        self.assertEqual(prod["custo_unitario_brl"], 45.96)
        self.assertAlmostEqual(prod["margem_brl"], 38.04, places=2)
        self.assertAlmostEqual(prod["lucro_proxy"], 380.4, places=1)


class TestAgenteMasterprintPetg(unittest.TestCase):
    def test_mensagem_tem_secoes(self):
        from agentes.filamentos.agente_monitor_masterprint_petg import montar_mensagem_telegram

        msg = montar_mensagem_telegram(
            {
                "total_anuncios_ativos": 3,
                "preco_min": 70,
                "preco_max": 110,
                "preco_medio": 90,
                "custo_padrao_1kg_brl": 45.96,
                "tabela_valida_em": "2026-07-23",
                "margem_media_brl": 30.0,
                "lucro_proxy_total": 5000,
                "vendas_totais": 200,
                "receita_proxy_total": 18000,
                "termos_varridos": 2,
                "mais_rentaveis": [
                    {
                        "titulo": "Masterprint PETG Preto",
                        "preco": 90,
                        "custo_unitario_brl": 45.96,
                        "margem_brl": 29.64,
                        "margem_pct": 32.9,
                        "quantidade_vendida": 100,
                        "lucro_proxy": 2964,
                        "receita_proxy": 9000,
                        "item_id": "MLB9",
                    }
                ],
                "maior_ganho": [
                    {
                        "titulo": "Masterprint PETG Azul",
                        "preco": 85,
                        "custo_unitario_brl": 45.96,
                        "margem_brl": 25.44,
                        "margem_pct": 29.9,
                        "quantidade_vendida": 40,
                        "lucro_proxy": 1017.6,
                        "receita_proxy": 3400,
                        "delta_vendas": 12,
                        "delta_receita": 1020,
                        "ganho_fonte": "delta_historico",
                        "item_id": "MLB8",
                    }
                ],
                "mais_vendidos": [],
            }
        )
        self.assertIn("Anúncios ativos: *3*", msg)
        self.assertIn("Mais rentáveis", msg)
        self.assertIn("margem real", msg)
        self.assertIn("Maior ganho", msg)
        self.assertIn("Masterprint PETG Preto", msg)
        self.assertIn("Custo tabela 1kg", msg)


if __name__ == "__main__":
    unittest.main()
