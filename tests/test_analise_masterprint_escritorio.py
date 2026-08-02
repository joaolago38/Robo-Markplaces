"""tests/test_analise_masterprint_escritorio.py"""
from __future__ import annotations

import unittest

from integracoes.escritorio import analise_masterprint_escritorio as an
from integracoes.escritorio import custos_masterprint_escritorio as custos


class TestCustosEscritorio(unittest.TestCase):
    def setUp(self):
        custos.limpar_cache_custos()

    def test_casa_pincel_permanente_caixa12(self):
        m = custos.casar_custo_anuncio(
            "Pincel Marcador Permanente Masterprint Preto Caixa com 12 Recarregavel"
        )
        self.assertIsNotNone(m)
        self.assertEqual(m["tipo"], "pincel_permanente")
        self.assertAlmostEqual(m["custo_unitario_brl"], 15.13, places=2)
        self.assertEqual(m["modo_custo"], "embalagem")

    def test_casa_pincel_quadro_recarregavel(self):
        m = custos.casar_custo_anuncio(
            "Pincel Quadro Branco Masterprint Azul Caixa 12 Recarregavel"
        )
        self.assertIsNotNone(m)
        self.assertEqual(m["tipo"], "pincel_quadro_branco")
        self.assertAlmostEqual(m["custo_unitario_brl"], 13.61, places=2)

    def test_casa_apagador(self):
        m = custos.casar_custo_anuncio("Apagador de Quadro com Ima Masterprint Azul")
        self.assertIsNotNone(m)
        self.assertEqual(m["tipo"], "apagador")
        self.assertAlmostEqual(m["custo_unitario_brl"], 2.73, places=2)

    def test_margem_apagador(self):
        # 15 * 0.84 - 2.73 = 9.87
        prod = custos.enriquecer_com_margem(
            {
                "titulo": "Apagador Quadro Masterprint Azul com Ima",
                "preco": 15.0,
                "quantidade_vendida": 20,
                "tipo": "apagador",
            },
            taxa_ml_pct=16.0,
        )
        self.assertAlmostEqual(prod["custo_unitario_brl"], 2.73, places=2)
        self.assertAlmostEqual(prod["margem_brl"], 9.87, places=2)
        self.assertAlmostEqual(prod["lucro_proxy"], 197.4, places=1)


class TestAnaliseEscritorio(unittest.TestCase):
    def test_filtra_masterprint_recarregavel(self):
        ok = an.classificar_masterprint_escritorio(
            {
                "item_id": "MLB1",
                "titulo": "Pincel Permanente Masterprint Preto Recarregavel Caixa 12",
                "preco": 29.9,
                "quantidade_vendida": 40,
            }
        )
        self.assertIsNotNone(ok)
        self.assertEqual(ok["tipo"], "pincel_permanente")

        outro = an.classificar_masterprint_escritorio(
            {
                "item_id": "MLB2",
                "titulo": "Pincel Permanente Faber Castell Preto",
                "preco": 20.0,
                "quantidade_vendida": 10,
            }
        )
        self.assertIsNone(outro)

        nao_rec = an.classificar_masterprint_escritorio(
            {
                "item_id": "MLB3",
                "titulo": "Pincel Permanente Masterprint Slim Nao Recarregavel",
                "preco": 18.0,
                "quantidade_vendida": 5,
            }
        )
        self.assertIsNone(nao_rec)

    def test_consolidar_com_margem(self):
        resultados = [
            {
                "ok": True,
                "produtos": [
                    {
                        "item_id": "MLB1",
                        "titulo": "Apagador Quadro Masterprint Azul",
                        "preco": 12.0,
                        "quantidade_vendida": 10,
                        "receita_proxy": 120.0,
                        "tipo": "apagador",
                        "marca": "Masterprint",
                    },
                    {
                        "item_id": "MLB2",
                        "titulo": "Pincel Quadro Branco Masterprint Preto Caixa com 12 Recarregavel",
                        "preco": 35.0,
                        "quantidade_vendida": 50,
                        "receita_proxy": 1750.0,
                        "tipo": "pincel_quadro_branco",
                        "marca": "Masterprint",
                    },
                ],
            }
        ]
        cons = an.consolidar_masterprint_escritorio(resultados, top_n=5)
        self.assertEqual(cons["total_anuncios_ativos"], 2)
        self.assertIn("apagador", cons["por_tipo"])
        self.assertIsNotNone(cons["mais_rentaveis"][0].get("margem_brl"))
        self.assertEqual(cons["mais_rentaveis"][0]["item_id"], "MLB2")


class TestAgenteEscritorio(unittest.TestCase):
    def test_mensagem_tem_secoes(self):
        from agentes.escritorio.agente_monitor_masterprint_escritorio import (
            montar_mensagem_telegram,
        )

        msg = montar_mensagem_telegram(
            {
                "total_anuncios_ativos": 2,
                "por_tipo": {"apagador": 1, "pincel_permanente": 1},
                "preco_min": 10,
                "preco_max": 40,
                "preco_medio": 25,
                "custos_referencia": {
                    "pincel_permanente_recarregavel_caixa12_brl": 15.13,
                    "pincel_quadro_branco_recarregavel_caixa12_brl": 13.61,
                    "apagador_quadro_ima_brl": 2.73,
                },
                "tabela_valida_em": "2026-07-23",
                "margem_media_brl": 12.0,
                "lucro_proxy_total": 800,
                "vendas_totais": 60,
                "receita_proxy_total": 2000,
                "termos_varridos": 3,
                "mais_rentaveis": [
                    {
                        "titulo": "Apagador Masterprint",
                        "tipo": "apagador",
                        "preco": 15,
                        "custo_unitario_brl": 2.73,
                        "margem_brl": 9.87,
                        "margem_pct": 65.8,
                        "quantidade_vendida": 20,
                        "lucro_proxy": 197.4,
                        "item_id": "MLB9",
                    }
                ],
                "maior_ganho": [],
                "mais_vendidos": [],
            }
        )
        self.assertIn("Panorama: *2* anúncios", msg)
        self.assertIn("AGIR — priorize margem", msg)
        self.assertIn("Apagador Masterprint", msg)
        self.assertIn("Custo:", msg)


if __name__ == "__main__":
    unittest.main()
