"""
tests/test_analise_loja_concorrente.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.ml import analise_loja_concorrente as al


class AnaliseLojaTests(unittest.TestCase):
    @patch.object(al, "buscar_perfil_loja", return_value={
        "ok": True,
        "seller_id": "1666381510",
        "nickname": "NOVAMIX_COMERCIAL",
        "level_id": "5_green",
        "power_seller_status": "platinum",
        "transactions_total": 71423,
        "cidade": "São Paulo",
        "estado": "BR-SP",
    })
    @patch.object(al, "coletar_anuncios_loja", return_value=[
        {
            "item_id": "MLB1",
            "titulo": "Kit 5 Esmaltes Impala Bailarina",
            "preco": 42.0,
            "quantidade_vendida": 10,
            "seller_id": "1666381510",
            "marcas": ["impala"],
        }
    ])
    @patch.object(al, "_comparar_com_catalogo", return_value=[
        {
            "sku": "IMP-BAIL-005",
            "nome": "Kit 5 Bailarina",
            "meu_preco": 48.9,
            "menor_preco_loja": 42.0,
            "gap_pct": 16.4,
            "anuncios_loja": 1,
            "amostra": [],
        }
    ])
    def test_analisar_loja(self, *_):
        out = al.analisar_loja("1666381510", nickname="NOVAMIX_COMERCIAL")
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_anuncios_coletados"], 1)
        self.assertEqual(out["preco_min"], 42.0)
        self.assertEqual(len(out["ameacas_preco"]), 1)
        msg = al.montar_mensagem_analise(out)
        self.assertIn("NOVAMIX", msg)
        self.assertIn("platinum", msg.lower() or "Platinum" in msg or "Líder" in msg)

    def test_filtrar_seller_em_coleta(self):
        rows = [
            {"item_id": "A", "titulo": "Kit Impala", "preco": 40, "seller_id": "1666381510"},
            {"item_id": "B", "titulo": "Kit Impala", "preco": 39, "seller_id": "999"},
        ]
        with patch.object(al.ml_client, "buscar_concorrentes_por_termo", return_value=rows):
            out = al.coletar_anuncios_loja("1666381510", termos=["kit impala"], limite_por_termo=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["item_id"], "A")


if __name__ == "__main__":
    unittest.main()
