# -*- coding: utf-8 -*-
"""tests/test_metricas_top_anuncios.py"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.filamentos import metricas_top_anuncios as m


class TestMetricasTopAnuncios(unittest.TestCase):
    @patch("integracoes.filamentos.metricas_top_anuncios.gauge")
    def test_emite_top_e_sellers(self, mock_gauge):
        anuncios = [
            {
                "item_id": "MLB111",
                "seller_id": "999",
                "quantidade_vendida": 100,
                "preco": 80,
                "receita_proxy": 8000,
                "marca": "Masterprint",
                "material": "PETG",
                "margem_brl": 30,
                "vendas_por_dia": 2.5,
                "catalog_date_created": "2024-01-01T00:00:00Z",
            },
            {
                "item_id": "MLB222",
                "seller_id": "888",
                "quantidade_vendida": 50,
                "preco": 70,
                "receita_proxy": 3500,
                "marca": "Masterprint",
                "material": "PETG",
                "margem_brl": 25,
            },
        ]
        out = m.emitir_top_anuncios("masterprint_petg", anuncios, top_n=5)
        self.assertEqual(out["top_anuncios"], 2)
        self.assertEqual(out["top_sellers"], 2)
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("masterprint_petg.top_vendas", nomes)
        self.assertIn("masterprint_petg.seller_vendas", nomes)
        self.assertIn("masterprint_petg.seller_vendas_dia", nomes)
        self.assertIn("masterprint_petg.top_margem_rank", nomes)
        for c in mock_gauge.call_args_list:
            tags = c.kwargs.get("tags") or []
            self.assertFalse(any(str(t).startswith("sku:") for t in tags))
            self.assertFalse(any(str(t).startswith("item:") for t in tags))

    @patch("integracoes.filamentos.metricas_top_anuncios.gauge")
    def test_rank_por_margem_quando_vendas_zero(self, mock_gauge):
        anuncios = [
            {
                "item_id": "MLB1",
                "seller_id": "1",
                "quantidade_vendida": 0,
                "preco": 90,
                "margem_brl": 40,
                "marca": "Masterprint",
                "material": "PETG",
            },
            {
                "item_id": "MLB2",
                "seller_id": "2",
                "quantidade_vendida": 0,
                "preco": 100,
                "margem_brl": 10,
                "marca": "Masterprint",
                "material": "PETG",
            },
        ]
        perfis = {
            "2": {"nickname": "loja_grande", "transactions_total": 50000},
            "1": {"nickname": "loja_pequena", "transactions_total": 100},
        }
        out = m.emitir_top_anuncios(
            "masterprint_petg", anuncios, top_n=5, sellers_perfil=perfis
        )
        self.assertEqual(out["sellers_perfil"], 2)
        # seller rank 1 deve ser o de mais transações
        seller_calls = [
            c
            for c in mock_gauge.call_args_list
            if c.args[0] == "masterprint_petg.seller_transacoes"
        ]
        self.assertTrue(seller_calls)
        tags0 = seller_calls[0].kwargs.get("tags") or []
        self.assertIn("seller:2", tags0)
        self.assertIn("rank:1", tags0)


if __name__ == "__main__":
    unittest.main()
