"""tests/test_publicar_kit_guerra.py"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.ml import publicar_kit_guerra as pub


class TestMontarPayload(unittest.TestCase):
    def test_mimo_titulo_e_sku(self):
        produto = {
            "sku": "IMP-MIMO-003",
            "nome": "Kit 3",
            "preco": 44.9,
            "valida_unidades": 10,
            "canais": {
                "mercadolivre": {
                    "titulo_anuncio": "outro",
                    "categoria_ml": "MLB1430",
                    "preco": 44.9,
                }
            },
        }
        with patch.dict(os.environ, {"ML_KIT_PICTURE_URLS": "https://img.example/a.jpg"}, clear=False):
            out = pub.montar_payload_item(produto, sku="IMP-MIMO-003")
        self.assertEqual(out["title"], pub.TITULO_MIMO_ML)
        self.assertEqual(out["seller_custom_field"], "IMP-MIMO-003")
        self.assertEqual(len(out["pictures"]), 1)

    def test_sem_fotos_nao_publica(self):
        produto = {
            "sku": "IMP-MIMO-003",
            "nome": "Kit 3",
            "preco": 44.9,
            "valida_unidades": 10,
            "canais": {"mercadolivre": {"item_id": "MLB_PREENCHER", "preco": 44.9, "categoria_ml": "MLB1430"}},
        }
        with patch.object(pub, "carregar_produtos_catalogo", return_value=[produto]):
            with patch.object(pub, "sku_pode_publicar_agora", return_value=(True, "ok")):
                with patch.dict(os.environ, {"ML_KIT_PICTURE_URLS": ""}, clear=False):
                    out = pub.publicar_sku("IMP-MIMO-003", executar=False)
        self.assertFalse(out["ok"])
        self.assertEqual(out["erro"], "sem_fotos")


if __name__ == "__main__":
    unittest.main()
