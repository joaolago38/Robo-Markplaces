# -*- coding: utf-8 -*-
"""tests/test_metricas_sellers_mercado.py"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.esmaltes import metricas_sellers_mercado as m


class TestMetricasSellersMercado(unittest.TestCase):
    @patch("integracoes.esmaltes.metricas_sellers_mercado.gauge")
    def test_rank_por_vendas_dia(self, mock_gauge):
        anuncios = [
            {
                "item_id": "MLB1",
                "seller_id": "111",
                "quantidade_vendida": 100,
                "vendas_por_dia": 4.0,
            },
            {
                "item_id": "MLB2",
                "seller_id": "111",
                "quantidade_vendida": 20,
                "vendas_por_dia": 1.0,
            },
            {
                "item_id": "MLB3",
                "seller_id": "222",
                "quantidade_vendida": 80,
                "vendas_por_dia": 2.0,
            },
        ]
        out = m.emitir_sellers_mercado("impala.batalha", anuncios, top_n=5)
        self.assertEqual(out["top_sellers"], 2)
        self.assertEqual(out["vendas_dia_amostra"], 3)
        self.assertEqual(out["seller_vendas_dia_max"], 5.0)
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("impala.batalha.seller_vendas_dia", nomes)
        self.assertIn("impala.batalha.seller_anuncios", nomes)
        vpd_calls = [
            c for c in mock_gauge.call_args_list if c.args[0] == "impala.batalha.seller_vendas_dia"
        ]
        tags0 = vpd_calls[0].kwargs.get("tags") or []
        self.assertIn("seller:111", tags0)
        self.assertIn("rank:1", tags0)
        self.assertEqual(vpd_calls[0].args[1], 5.0)
        for c in mock_gauge.call_args_list:
            tags = c.kwargs.get("tags") or []
            self.assertFalse(any(str(t).startswith("sku:") for t in tags))
            self.assertFalse(any(str(t).startswith("item:") for t in tags))
            self.assertFalse(any(str(t).startswith("termo:") for t in tags))

    @patch("integracoes.esmaltes.metricas_sellers_mercado.gauge")
    def test_estima_vpd_pela_data(self, mock_gauge):
        anuncios = [
            {
                "item_id": "MLB9",
                "seller_id": "333",
                "quantidade_vendida": 100,
                "catalog_date_created": "2024-01-01T00:00:00Z",
            }
        ]
        out = m.emitir_sellers_mercado("cruzeiro.mercado", anuncios, top_n=3)
        self.assertEqual(out["vendas_dia_amostra"], 1)
        self.assertGreater(out["seller_vendas_dia_max"], 0)
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("cruzeiro.mercado.seller_vendas_dia", nomes)

    @patch("integracoes.esmaltes.metricas_sellers_mercado.gauge")
    def test_rank_por_transacoes_quando_vendas_zero(self, mock_gauge):
        anuncios = [
            {"item_id": "MLB1", "seller_id": "1", "quantidade_vendida": 0},
            {"item_id": "MLB2", "seller_id": "2", "quantidade_vendida": 0},
        ]
        perfis = {
            "2": {"nickname": "loja_grande", "transactions_total": 50000},
            "1": {"nickname": "loja_pequena", "transactions_total": 100},
        }
        m.emitir_sellers_mercado(
            "impala.batalha", anuncios, top_n=5, sellers_perfil=perfis
        )
        vpd_calls = [
            c
            for c in mock_gauge.call_args_list
            if c.args[0] == "impala.batalha.seller_vendas_dia"
        ]
        tags0 = vpd_calls[0].kwargs.get("tags") or []
        self.assertIn("seller:2", tags0)
        self.assertIn("rank:1", tags0)
        self.assertIn("nick:loja_grande", tags0)

    @patch("integracoes.esmaltes.metricas_sellers_mercado.gauge")
    def test_vazio_emite_zeros(self, mock_gauge):
        out = m.emitir_sellers_mercado("impala.batalha", [])
        self.assertEqual(out["top_sellers"], 0)
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("impala.batalha.seller_vendas_dia_max", nomes)
        self.assertIn("impala.batalha.top_sellers_emitidos", nomes)

    def test_prefixo_vazio(self):
        out = m.emitir_sellers_mercado("", [{"seller_id": "1"}])
        self.assertEqual(out["top_sellers"], 0)


if __name__ == "__main__":
    unittest.main()
