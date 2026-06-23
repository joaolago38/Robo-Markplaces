import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes import sincronizar_estoque_marketplaces as sync


def _produto_ml(sku: str, estoque_canal: int, item_id: str = "MLB123") -> dict:
    return {
        "sku": sku,
        "canais": {
            "mercadolivre": {
                "ativo": True,
                "item_id": item_id,
                "estoque": estoque_canal,
            }
        },
    }


def _produto_shopee(sku: str, estoque_canal: int, item_id: int = 999) -> dict:
    return {
        "sku": sku,
        "canais": {
            "shopee": {
                "ativo": True,
                "item_id": item_id,
                "estoque": estoque_canal,
            }
        },
    }


def _produto_magalu(sku: str, estoque_canal: int) -> dict:
    return {
        "sku": sku,
        "canais": {
            "magalu": {
                "ativo": True,
                "sku": sku,
                "estoque": estoque_canal,
            }
        },
    }


class TestSincronizarEstoqueMarketplaces(unittest.TestCase):
    @patch.object(sync, "alertar_gestor")
    @patch.object(sync, "buscar_produto")
    def test_dry_run_detecta_ajuste_sem_escrita(self, mock_buscar, mock_gestor):
        mock_buscar.return_value = {"sku": "SKU-A", "estoque": 5}
        produtos = [_produto_ml("SKU-A", 2)]

        with patch.object(sync, "atualizar_estoque_ml") as mock_ml:
            out = sync.executar(produtos=produtos, dry_run=True)

        self.assertTrue(out["dry_run"])
        self.assertEqual(out["total_ajustes"], 1)
        self.assertEqual(out["ajustes"][0]["estoque_bling"], 5)
        self.assertEqual(out["ajustes"][0]["estoque_anterior_canal"], 2)
        self.assertIsNone(out["ajustes"][0]["aplicado"])
        mock_ml.assert_not_called()
        mock_gestor.assert_called_once()

    @patch.object(sync, "_salvar_catalogo")
    @patch.object(sync, "alertar_gestor")
    @patch.object(sync, "atualizar_estoque_ml", return_value=True)
    @patch.object(sync, "buscar_produto")
    def test_aplica_ajuste_ml_e_atualiza_catalogo(self, mock_buscar, mock_ml, mock_gestor, mock_salvar):
        mock_buscar.return_value = {"sku": "SKU-B", "estoque": 8}
        produtos = [_produto_ml("SKU-B", 3)]

        out = sync.executar(produtos=produtos, dry_run=False)

        self.assertFalse(out["dry_run"])
        self.assertTrue(out["ajustes"][0]["aplicado"])
        mock_ml.assert_called_once_with("MLB123", 8)
        mock_salvar.assert_called_once()
        self.assertEqual(produtos[0]["canais"]["mercadolivre"]["estoque"], 8)

    @patch.object(sync, "_salvar_catalogo")
    @patch.object(sync, "alertar_gestor")
    @patch.object(sync, "atualizar_estoque_shopee", return_value=True)
    @patch.object(sync, "buscar_produto")
    def test_aplica_ajuste_shopee(self, mock_buscar, mock_shopee, mock_gestor, mock_salvar):
        mock_buscar.return_value = {"sku": "SKU-S", "estoque": 4}
        produtos = [_produto_shopee("SKU-S", 1)]

        out = sync.executar(produtos=produtos, dry_run=False)

        mock_shopee.assert_called_once_with(999, 4)
        self.assertEqual(out["total_ajustes"], 1)

    @patch.object(sync, "_salvar_catalogo")
    @patch.object(sync, "alertar_gestor")
    @patch.object(sync, "atualizar_estoque_magalu", return_value=True)
    @patch.object(sync, "buscar_produto")
    def test_aplica_ajuste_magalu(self, mock_buscar, mock_magalu, mock_gestor, mock_salvar):
        mock_buscar.return_value = {"sku": "SKU-M", "estoque": 6}
        produtos = [_produto_magalu("SKU-M", 2)]

        out = sync.executar(produtos=produtos, dry_run=False)

        mock_magalu.assert_called_once_with("SKU-M", 6)
        self.assertEqual(out["total_ajustes"], 1)

    @patch.object(sync, "alertar_gestor")
    @patch.object(sync, "buscar_produto")
    def test_pula_produto_sem_estoque_bling(self, mock_buscar, mock_gestor):
        mock_buscar.return_value = {"sku": "SKU-X", "estoque": None}
        produtos = [_produto_ml("SKU-X", 5)]

        with patch.object(sync, "atualizar_estoque_ml") as mock_ml:
            out = sync.executar(produtos=produtos, dry_run=False)

        self.assertEqual(out["total_ajustes"], 0)
        self.assertIn("SKU-X", out["produtos_sem_estoque_bling"])
        mock_ml.assert_not_called()
        mock_gestor.assert_not_called()

    @patch.object(sync, "_salvar_catalogo")
    @patch.object(sync, "alertar_critico")
    @patch.object(sync, "pausar_anuncio", return_value=True)
    @patch.object(sync, "alertar_gestor")
    @patch.object(sync, "atualizar_estoque_ml", return_value=True)
    @patch.object(sync, "buscar_produto")
    def test_alerta_critico_quando_estoque_zero(
        self, mock_buscar, mock_ml, mock_gestor, mock_pausar, mock_critico, mock_salvar
    ):
        mock_buscar.return_value = {"sku": "SKU-Z", "estoque": 0}
        produtos = [_produto_ml("SKU-Z", 3)]

        sync.executar(produtos=produtos, dry_run=False)

        mock_critico.assert_called_once()
        mock_pausar.assert_called_once_with("MLB123", dry_run=False, confirmar=True)


if __name__ == "__main__":
    unittest.main()
