"""tests/test_metricas_batalha_impala.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import metricas_batalha_impala as b


class TestBatalhaImpala(unittest.TestCase):
    def setUp(self):
        self.kits = [
            {
                "item_id": "MLB111",
                "titulo": "Kit 10 Esmaltes Impala Sortidos Atacado",
                "marca": "Impala",
                "qtd_kit": 10,
                "preco": 45.0,
                "quantidade_vendida": 120,
                "seller_id": "S1",
            },
            {
                "item_id": "MLB222",
                "titulo": "Kit 10 Esmaltes Impala Nude",
                "marca": "Impala",
                "qtd_kit": 10,
                "preco": 52.0,
                "quantidade_vendida": 40,
                "seller_id": "S2",
            },
            {
                "item_id": "MLB333",
                "titulo": "Kit 15 Esmaltes Impala Vermelho Rosa",
                "marca": "Impala",
                "qtd_kit": 15,
                "preco": 70.0,
                "quantidade_vendida": 200,
                "seller_id": "S1",
            },
            {
                "item_id": "MLB999",
                "titulo": "Kit 10 Esmaltes Anita",
                "marca": "Anita",
                "qtd_kit": 10,
                "preco": 55.0,
                "quantidade_vendida": 90,
                "seller_id": "S9",
            },
        ]
        self.produtos = [
            {
                "sku": "IMP-SORT-010",
                "prioridade": "P0",
                "nome": "Kit 10 Esmaltes Impala Sortidas",
                "preco": 48.0,
                "preco_ml_mercado": 48.0,
                "cores": [{"nome": f"c{i}"} for i in range(10)],
                "canais": {"mercadolivre": {"preco": 48.0, "item_id": "MLB_PREENCHER"}},
            },
            {
                "sku": "IMP-VR-015",
                "prioridade": "P0",
                "nome": "Kit 15 Esmaltes Impala Vermelho",
                "preco": 69.9,
                "preco_ml_mercado": 72.9,
                "cores": [{"nome": f"c{i}"} for i in range(15)],
                "canais": {"mercadolivre": {"preco": 69.9, "item_id": "MLB_PREENCHER"}},
            },
        ]
        self.guerra = [
            {"sku": "IMP-SORT-010", "papel": "atacado"},
            {"sku": "IMP-VR-015", "papel": "giro"},
        ]

    def test_extrair_so_impala(self):
        out = b.extrair_anuncios_impala(self.kits)
        self.assertEqual(len(out), 3)

    @patch("integracoes.esmaltes.metricas_batalha_impala.carregar_skus_guerra")
    @patch("integracoes.esmaltes.metricas_batalha_impala.carregar_produtos_catalogo")
    def test_montar_batalha_gap(self, mock_prod, mock_guerra):
        mock_prod.return_value = self.produtos
        mock_guerra.return_value = self.guerra
        anuncios = b.extrair_anuncios_impala(self.kits)
        bat = b.montar_batalha(anuncios_impala=anuncios, produtos=self.produtos, guerra=self.guerra)
        self.assertEqual(bat["anuncios_unicos"], 3)
        self.assertEqual(bat["sellers_unicos"], 2)
        by = {c["sku"]: c for c in bat["comparacoes"]}
        # nosso 48 vs rival min 45 → gap positivo
        self.assertGreater(by["IMP-SORT-010"]["gap_pct"], 0)
        self.assertEqual(by["IMP-SORT-010"]["rivais_no_tam"], 2)
        self.assertEqual(by["IMP-VR-015"]["rivais_no_tam"], 1)

    @patch("integracoes.esmaltes.metricas_batalha_impala.incrementar")
    @patch("integracoes.esmaltes.metricas_batalha_impala.gauge")
    @patch("integracoes.esmaltes.metricas_batalha_impala.carregar_skus_guerra")
    @patch("integracoes.esmaltes.metricas_batalha_impala.carregar_produtos_catalogo")
    def test_emitir(self, mock_prod, mock_guerra, mock_gauge, mock_inc):
        mock_prod.return_value = self.produtos
        mock_guerra.return_value = self.guerra
        out = b.emitir_metricas_batalha_impala(kits_unicos=self.kits)
        self.assertTrue(out["ok"])
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("impala.batalha.anuncios_unicos", nomes)
        self.assertIn("impala.batalha.gap_vs_rival_pct", nomes)
        for c in mock_gauge.call_args_list:
            tags = c.kwargs.get("tags") or []
            self.assertFalse(any(str(t).startswith("sku:") for t in tags))
        mock_inc.assert_any_call("impala.batalha.rodadas")


if __name__ == "__main__":
    unittest.main()
