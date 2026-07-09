"""
tests/test_promocoes_manicures.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.social import promocoes_manicures as pm

_PRODUTO = {
    "sku": "IMP-MIMO-003",
    "nome": "Kit 3 Mimo + Carmed Impala",
    "preco": 44.9,
    "canais": {
        "mercadolivre": {
            "ativo": True,
            "preco": 44.9,
            "item_id": "MLB1234567890",
            "titulo_anuncio": "Kit Impala Mimo",
        }
    },
}


class PromocoesManicuresTests(unittest.TestCase):
    @patch.object(pm, "carregar_produtos_catalogo", return_value=[_PRODUTO])
    def test_montar_mensagem_ok(self, *_):
        campanha = {
            "id": "kit-3",
            "sku": "IMP-MIMO-003",
            "preco_de": 52.9,
            "template": "*{produto}* R$ {preco} — {link}",
        }
        out = pm.montar_mensagem_campanha(campanha)
        self.assertTrue(out["ok"])
        self.assertIn("44,90", out["texto"])
        self.assertIn("MLB1234567890", out["link_ml"])
        self.assertNotIn("*", out["texto_whatsapp"])

    @patch.object(pm, "carregar_produtos_catalogo", return_value=[])
    def test_montar_mensagem_sku_inexistente(self, *_):
        out = pm.montar_mensagem_campanha({"id": "x", "sku": "NAO-EXISTE", "template": "{produto}"})
        self.assertFalse(out["ok"])
        self.assertIn("sku não encontrado", out["motivo"])

    def test_escolher_campanha_rotacao(self):
        campanhas = [
            {"id": "a", "prioridade": 1},
            {"id": "b", "prioridade": 2},
            {"id": "c", "prioridade": 3},
        ]
        self.assertEqual(pm.escolher_campanha(campanhas, ultimo_id=None)["id"], "a")
        self.assertEqual(pm.escolher_campanha(campanhas, ultimo_id="a")["id"], "b")
        self.assertEqual(pm.escolher_campanha(campanhas, ultimo_id="c")["id"], "a")

    @patch.object(pm, "ler_json", return_value=[{"id": "c1", "ativo": True}])
    def test_carregar_campanhas_ativas(self, *_):
        with patch.object(pm, "ROOT", pm.ROOT):
            out = pm.carregar_campanhas()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "c1")


if __name__ == "__main__":
    unittest.main()
