import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.marketplaces import sinais_comprador as sc


class SinaisCompradorTests(unittest.TestCase):
    def test_item_id_invalido_preencher(self):
        self.assertFalse(sc._item_id_valido("MLB_PREENCHER"))
        self.assertFalse(sc._item_id_valido(""))
        self.assertTrue(sc._item_id_valido("MLB123456"))

    @patch("integracoes.ml.ml_client.buscar_concorrentes_por_termo")
    def test_menor_concorrente_por_termo(self, mock_busca):
        mock_busca.return_value = [
            {"preco": 55.0, "quantidade_vendida": 10, "titulo": "A"},
            {"preco": 49.0, "quantidade_vendida": 3, "titulo": "B"},
        ]
        out = sc._menor_concorrente_por_termo("kit impala")
        self.assertEqual(out["menor_preco"], 49.0)
        self.assertEqual(out["lider_preco"], 55.0)
        self.assertEqual(out["quantidade_vendida_lider"], 10)

    @patch("integracoes.ml.ml_client._enabled", return_value=False)
    def test_coletar_sinais_ml_desabilitado(self, *_):
        out = sc.coletar_sinais_mercadolivre({"item_id": "MLB1"}, sku="SKU1")
        self.assertFalse(out["configurado"])
        self.assertIn("motivo", out)

    @patch("integracoes.ml.ml_client.buscar_menor_preco_concorrente", return_value=42.0)
    @patch("integracoes.ml.ml_client.buscar_sugestao_preco", return_value={"preco_sugerido": 45.0})
    @patch(
        "integracoes.ml.ml_client.buscar_metricas_item",
        return_value={"visitas_7d": 5, "visitas_30d": 20, "preco": 50.0, "estoque": 1},
    )
    @patch("integracoes.ml.ml_client._enabled", return_value=True)
    def test_coletar_sinais_ml_com_item(self, *_):
        with patch("agentes.painel_item._somar_vendas_do_item", return_value={"unidades_vendidas": 2}):
            out = sc.coletar_sinais_mercadolivre(
                {"item_id": "MLB999"},
                sku="SKU9",
                termo_busca="kit impala",
            )
        self.assertEqual(out["visitas_7d"], 5)
        self.assertEqual(out["unidades_vendidas_7d"], 2)
        self.assertEqual(out["preco_concorrente_vivo"], 42.0)

    @patch("integracoes.shopee.shopee_client._enabled", return_value=True)
    @patch("integracoes.shopee.shopee_client.obter_saude_conta", return_value={"ok": True})
    def test_coletar_sinais_generico_shopee(self, *_):
        out = sc.coletar_sinais_generico("shopee", {"termo_busca": "kit"}, sku="SKU1")
        self.assertTrue(out["configurado"])
        self.assertEqual(out["saude"], {"ok": True})

    def test_coletar_sinais_rota_mercadolivre(self):
        with patch.object(sc, "coletar_sinais_mercadolivre", return_value={"marketplace": "mercadolivre"}) as mock_ml:
            out = sc.coletar_sinais("mercadolivre", {}, sku="X")
            self.assertEqual(out["marketplace"], "mercadolivre")
            mock_ml.assert_called_once()


if __name__ == "__main__":
    unittest.main()
