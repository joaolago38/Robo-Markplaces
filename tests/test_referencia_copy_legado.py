"""tests/test_referencia_copy_legado.py — copy das bolsas como estrutura, não produto."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.ml import referencia_copy_legado as ref


_BOLSAS = [
    {
        "item_id": "MLB-B1",
        "titulo": "Bolsa Feminina Couro Legitimo Mariart Shopper",
        "sold_quantity": 80,
        "status": "active",
    },
    {
        "item_id": "MLB-B2",
        "titulo": "Carteira Feminina Mariart Couro Bovino",
        "sold_quantity": 20,
        "status": "paused",
    },
    {
        "item_id": "MLB-K",
        "titulo": "Kit Esmalte Impala",
        "sold_quantity": 1,
        "sku": "IMP-MIMO-003",
        "status": "active",
    },
]


class TestPadroesTitulo(unittest.TestCase):
    def test_extrai_top_por_vendas(self):
        pad = ref.extrair_padroes_titulo(_BOLSAS[:2])
        self.assertEqual(pad["n"], 2)
        self.assertEqual(pad["top"][0]["item_id"], "MLB-B1")
        self.assertGreaterEqual(pad["chars_medio"], 30)
        self.assertIn("bolsa", pad["nao_transferir"])

    def test_bloco_contexto_estrutura_nao_produto(self):
        pad = ref.extrair_padroes_titulo(_BOLSAS[:2])
        pad["regras_claude"] = {
            "estrutura": "busca + atributo + marca + público",
            "regras": [{"regra": "Preencher 60 caracteres", "evidencia": "Shopper"}],
            "aviso": "Não copiar bolsa para esmalte",
        }
        bloco = ref.montar_bloco_contexto(pad)
        self.assertIn("REFERÊNCIA DE COPY", bloco)
        self.assertIn("Não transferir", bloco)
        self.assertIn("mariart", bloco.lower())
        self.assertIn("busca + atributo", bloco)

    def test_bloco_vazio_sem_amostra(self):
        self.assertEqual(ref.montar_bloco_contexto({"n": 0}), "")
        self.assertEqual(ref.montar_bloco_contexto(None), "")

    def test_titulo_impala_nao_pode_ter_bolsa(self):
        self.assertTrue(ref.titulo_tem_palavra_bolsa("Kit Bolsa Impala Esmalte"))
        self.assertTrue(ref.titulo_tem_palavra_bolsa("Kit Couro Legitimo Impala"))
        self.assertFalse(ref.titulo_tem_palavra_bolsa("Kit 4 Esmaltes Impala Perolado Manicure"))


class TestColetar(unittest.TestCase):
    @patch.object(ref, "analisar_padroes_com_claude", return_value={"estrutura": "X", "regras": []})
    @patch.object(ref, "escrever_json_atomico")
    @patch.object(ref, "filtrar_anuncios_legado", return_value=(_BOLSAS[:2], {"legado": 2}))
    def test_coletar_ao_vivo(self, _fil, _w, _claude):
        with patch("integracoes.ml.ml_client.listar_meus_anuncios", return_value=_BOLSAS):
            out = ref.coletar_referencia_copy_legado(ao_vivo=True, usar_claude=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["n"], 2)
        self.assertEqual(out["fonte"], "ml_ao_vivo")
        self.assertEqual(out["regras_claude"]["estrutura"], "X")

    @patch.object(ref, "ler_json", return_value={"n": 3, "fonte": "snapshot", "top": []})
    def test_coletar_cai_no_snapshot(self, _ler):
        with patch("integracoes.ml.ml_client.listar_meus_anuncios", return_value=[]):
            out = ref.coletar_referencia_copy_legado(ao_vivo=True, usar_claude=False)
        self.assertEqual(out["n"], 3)
        self.assertEqual(out["fonte"], "snapshot")

    @patch.object(ref, "perguntar_estruturado", create=True)
    def test_claude_sem_top_nao_chama(self, mock_p):
        self.assertIsNone(ref.analisar_padroes_com_claude({"top": []}))
        mock_p.assert_not_called()


if __name__ == "__main__":
    unittest.main()
