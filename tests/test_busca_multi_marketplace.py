"""
tests/test_busca_multi_marketplace.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.marketplaces import busca_multi_marketplace as mod


class BuscaMultiMarketplaceTests(unittest.TestCase):
    @patch.object(mod, "_buscar_externo")
    @patch.object(mod, "_buscar_ml")
    def test_buscar_todos_marketplaces_deduplica(self, mock_ml, mock_ext):
        mock_ml.return_value = [
            {"item_id": "MLB1", "titulo": "A", "preco": 10, "marketplace": "mercadolivre"},
        ]
        mock_ext.return_value = [
            {"item_id": "MAG1", "titulo": "B", "preco": 20, "marketplace": "magalu"},
            {"item_id": "MAG2", "titulo": "C", "preco": 15, "marketplace": "magalu"},
        ]
        out = mod.buscar_todos_marketplaces(
            "acetona",
            limite=10,
            marketplaces=["mercadolivre", "magalu"],
        )
        self.assertEqual(len(out), 3)
        mock_ml.assert_called_once()
        mock_ext.assert_called_once()

    def test_resumo_por_marketplace(self):
        resumo = mod.resumo_por_marketplace(
            [
                {"marketplace": "magalu", "preco": 20, "quantidade_vendida": 0},
                {"marketplace": "mercadolivre", "preco": 10, "quantidade_vendida": 5},
                {"marketplace": "mercadolivre", "preco": 30, "quantidade_vendida": 3},
            ]
        )
        self.assertEqual(len(resumo), 2)
        ml = next(r for r in resumo if r["marketplace"] == "mercadolivre")
        self.assertEqual(ml["anuncios"], 2)
        self.assertEqual(ml["vendidos"], 8)
        self.assertEqual(ml["preco_medio"], 20.0)

    @patch("core.config.ESMALTES_BUSCA_MULTI_MARKETPLACE", False)
    def test_resolver_fn_busca_esmaltes_so_ml(self):
        from integracoes.ml import ml_client

        fn = mod.resolver_fn_busca_esmaltes()
        self.assertIs(fn, ml_client.buscar_concorrentes_por_termo)

    def test_formatar_secao_por_marketplace(self):
        txt = mod.formatar_secao_por_marketplace(
            {
                "por_marketplace": [
                    {"label": "Magalu", "anuncios": 3, "preco_medio": 18.5},
                ]
            },
            fmt_brl=lambda v: f"R${v}",
        )
        self.assertIn("Por marketplace", txt)
        self.assertIn("Magalu", txt)


if __name__ == "__main__":
    unittest.main()
