"""tests/test_produto_lookup_claim.py — MLB→SKU e exclusão mútua de chat."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import chat_claim
from core import produto_lookup as pl


class TestProdutoLookup(unittest.TestCase):
    def test_item_placeholder_invalido(self):
        self.assertFalse(pl.item_id_ml_valido("MLB_PREENCHER"))
        self.assertTrue(pl.item_id_ml_valido("MLB1234567890"))

    @patch.object(pl, "carregar_produtos_catalogo")
    def test_sku_por_mlb(self, mock_cat):
        mock_cat.return_value = [
            {
                "sku": "KIT3",
                "nome": "Kit 3",
                "canais": {"mercadolivre": {"ativo": True, "item_id": "MLB999888777"}},
            }
        ]
        self.assertEqual(pl.sku_por_item_id_ml("MLB999888777"), "KIT3")

    @patch.object(pl, "carregar_produtos_catalogo")
    @patch("integracoes.bling.bling_client.buscar_produto")
    def test_buscar_via_mlb_mapeado(self, mock_bling, mock_cat):
        mock_cat.return_value = [
            {
                "sku": "KIT3",
                "nome": "Kit 3",
                "canais": {"mercadolivre": {"ativo": True, "item_id": "MLB111", "estoque": 5, "preco": 44.9}},
            }
        ]
        mock_bling.return_value = {"nome": "Kit 3", "sku": "KIT3", "estoque": 5, "preco": 44.9}
        out = pl.buscar_produto_por_ref("MLB111", canal="mercadolivre")
        mock_bling.assert_called_once_with("KIT3")
        self.assertEqual(out["sku"], "KIT3")

    @patch.object(pl, "carregar_produtos_catalogo")
    def test_listar_placeholders(self, mock_cat):
        mock_cat.return_value = [
            {
                "sku": "X",
                "ativo": True,
                "nome": "Kit",
                "canais": {"mercadolivre": {"ativo": True, "item_id": "MLB_PREENCHER"}},
            }
        ]
        ruins = pl.listar_ativos_com_mlb_placeholder()
        self.assertEqual(len(ruins), 1)
        self.assertEqual(ruins[0]["sku"], "X")


class TestChatClaim(unittest.TestCase):
    def test_segundo_agente_bloqueado(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.json"
            with patch.object(chat_claim, "CLAIM_PATH", path):
                self.assertTrue(chat_claim.tentar_claim("mercadolivre", "q1", agente="chat_ml"))
                self.assertFalse(
                    chat_claim.tentar_claim("mercadolivre", "q1", agente="conversao_manicures")
                )
                self.assertTrue(chat_claim.tentar_claim("mercadolivre", "q1", agente="chat_ml"))


if __name__ == "__main__":
    unittest.main()
