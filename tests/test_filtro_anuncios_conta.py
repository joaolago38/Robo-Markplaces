"""tests/test_filtro_anuncios_conta.py — ignora bolsas/legado, mantém Impala."""
from __future__ import annotations

import unittest

from integracoes.ml.filtro_anuncios_conta import (
    anuncio_fora_do_foco,
    filtrar_anuncios_foco,
    filtrar_anuncios_legado,
    palavras_nao_transferir,
    reset_ultimo_filtro,
    sku_do_foco,
    ultimo_filtro_anuncios,
)

REGRAS = {
    "ativo": True,
    "sku_prefixos_foco": ["IMP-", "CRZ-", "BUNDLE-"],
    "titulo_contem": ["bolsa", "carteira", "mariart", "shopper", "scarpin", "sapato"],
    "sku_contem": ["mariart"],
    "category_ids": [],
    "titulo_legado": ["controle remoto ppa"],
}


class TestFiltroAnunciosConta(unittest.TestCase):
    def setUp(self):
        reset_ultimo_filtro()

    def test_sku_foco_impala(self):
        self.assertTrue(sku_do_foco("IMP-MIMO-003"))
        self.assertTrue(sku_do_foco("crz-1"))
        self.assertFalse(sku_do_foco("SKU-A"))
        self.assertFalse(sku_do_foco(""))

    def test_ignora_bolsa_mariart(self):
        motivo = anuncio_fora_do_foco(
            {
                "item_id": "MLB1",
                "titulo": "Bolsa Feminina Couro Legitimo Mariart Shopper",
                "sku": "",
            },
            REGRAS,
        )
        self.assertIsNotNone(motivo)
        self.assertIn("titulo", str(motivo))

    def test_mantem_kit_impala(self):
        self.assertIsNone(
            anuncio_fora_do_foco(
                {
                    "item_id": "MLB2",
                    "titulo": "Kit Esmalte Impala Sortidos",
                    "sku": "IMP-SORT-006",
                },
                REGRAS,
            )
        )

    def test_sku_foco_vence_titulo_bolsa(self):
        self.assertIsNone(
            anuncio_fora_do_foco(
                {
                    "item_id": "MLB3",
                    "titulo": "Bolsa kit promocional",
                    "sku": "IMP-MIMO-003",
                },
                REGRAS,
            )
        )

    def test_ignora_scarpin_legado(self):
        motivo = anuncio_fora_do_foco(
            {"titulo": "Sapato Feminino Scarpin Vermelho 37", "sku": ""},
            REGRAS,
        )
        self.assertIsNotNone(motivo)

    def test_ignora_legado_ppa(self):
        motivo = anuncio_fora_do_foco(
            {"titulo": "Controle Remoto PPA Tok", "sku": ""},
            REGRAS,
        )
        self.assertTrue(str(motivo).startswith("legado:"))

    def test_filtrar_separa_bolsas(self):
        mantidos, stats = filtrar_anuncios_foco(
            [
                {"item_id": "MLB-B", "titulo": "Carteira Mariart", "sku": ""},
                {"item_id": "MLB-K", "titulo": "Kit MIMO Impala", "sku": "IMP-MIMO-003"},
            ],
            regras=REGRAS,
        )
        self.assertEqual([a["item_id"] for a in mantidos], ["MLB-K"])
        self.assertEqual(stats["ignorados"], 1)
        self.assertEqual(stats["mantidos"], 1)
        self.assertEqual(ultimo_filtro_anuncios()["ignorados"], 1)

    def test_regras_inativas_nao_filtram(self):
        regras = {**REGRAS, "ativo": False}
        itens = [{"item_id": "MLB-B", "titulo": "Bolsa Mariart", "sku": ""}]
        self.assertIsNone(anuncio_fora_do_foco(itens[0], regras))
        mantidos, stats = filtrar_anuncios_foco(itens, regras=regras)
        self.assertEqual(len(mantidos), 1)
        self.assertEqual(stats["ignorados"], 0)

    def test_filtrar_legado_inverso_do_foco(self):
        legado, stats = filtrar_anuncios_legado(
            [
                {"item_id": "MLB-B", "titulo": "Carteira Mariart", "sku": ""},
                {"item_id": "MLB-K", "titulo": "Kit MIMO Impala", "sku": "IMP-MIMO-003"},
            ],
            regras=REGRAS,
        )
        self.assertEqual([a["item_id"] for a in legado], ["MLB-B"])
        self.assertEqual(stats["legado"], 1)
        self.assertEqual(stats["foco"], 1)

    def test_palavras_nao_transferir(self):
        palavras = palavras_nao_transferir(REGRAS)
        self.assertIn("bolsa", palavras)
        self.assertIn("mariart", palavras)

    def test_ignora_por_categoria(self):
        regras = {**REGRAS, "category_ids": ["MLB1924"]}
        motivo = anuncio_fora_do_foco(
            {"titulo": "Produto X", "sku": "", "category_id": "MLB1924"},
            regras,
        )
        self.assertEqual(motivo, "categoria:MLB1924")


if __name__ == "__main__":
    unittest.main()
