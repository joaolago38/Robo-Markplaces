"""tests/test_tipo_anuncio_ml.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.ml import analise_anuncio_concorrente as aa
from integracoes.ml import ml_client
from integracoes.ml import tipo_anuncio_ml as tipo


class TestTipoAnuncioMl(unittest.TestCase):
    def test_prateleira_premium_e_classico(self):
        self.assertEqual(tipo.prateleira("gold_pro"), "premium")
        self.assertEqual(tipo.prateleira("gold_special"), "classico")
        self.assertEqual(tipo.rotulo_prateleira("gold_pro"), "Premium")
        self.assertEqual(tipo.rotulo_prateleira("gold_special"), "Clássico")

    def test_mesma_prateleira_fail_open(self):
        self.assertTrue(tipo.mesma_prateleira("gold_pro", ""))
        self.assertTrue(tipo.mesma_prateleira("", "gold_special"))
        self.assertFalse(tipo.mesma_prateleira("gold_pro", "gold_special"))
        self.assertTrue(tipo.mesma_prateleira("gold_pro", "gold_premium"))

    def test_full_e_lider_nao_se_confundem(self):
        self.assertTrue(tipo.anuncio_e_full({"logistic_type": "fulfillment"}))
        self.assertTrue(tipo.anuncio_e_full({"shipping": {"logistic_type": "fulfillment"}}))
        self.assertFalse(tipo.anuncio_e_full({"listing_type_id": "gold_pro"}))
        self.assertFalse(tipo.algum_anuncio_full([{"listing_type_id": "gold_special"}]))

    def test_contar_prateleiras(self):
        out = tipo.contar_prateleiras(
            [
                {"listing_type_id": "gold_pro"},
                {"listing_type_id": "gold_special"},
                {"listing_type_id": "gold_special"},
            ]
        )
        self.assertEqual(out["premium"], 1)
        self.assertEqual(out["classico"], 2)

    def test_taxa_estimada_por_tipo(self):
        self.assertEqual(tipo.taxa_estimada_pct("gold_pro"), 18.0)
        self.assertEqual(tipo.taxa_estimada_pct("gold_special"), 12.0)
        self.assertEqual(tipo.taxa_estimada_pct(""), 13.0)

    def test_montar_metricas_usa_taxa_do_tipo(self):
        m = aa.montar_metricas(preco=44.9, vendas=0, listing_type_id="gold_pro")
        self.assertEqual(m["taxa_estimada_pct"], 18.0)
        m2 = aa.montar_metricas(preco=44.9, vendas=0, listing_type_id="gold_special")
        self.assertEqual(m2["taxa_estimada_pct"], 12.0)


class TestMenorPrecoMesmaPrateleira(unittest.TestCase):
    def setUp(self):
        ml_client._cache_concorrentes.clear()
        ml_client._cache_item_tipo.clear()
        self._sid = patch.object(ml_client, "ML_SELLER_ID", "111")
        self._sid.start()

    def tearDown(self):
        self._sid.stop()

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ignora_classico_quando_nosso_e_premium(self, _en, mock_request):
        item = _resp(
            {
                "catalog_product_id": "CAT1",
                "listing_type_id": "gold_pro",
            }
        )
        rivais = _resp(
            {
                "results": [
                    {"seller_id": 9, "price": 22.0, "listing_type_id": "gold_special"},
                    {"seller_id": 8, "price": 50.0, "listing_type_id": "gold_pro"},
                ]
            }
        )
        mock_request.side_effect = [item, rivais]
        mesma = ml_client.buscar_menor_preco_concorrente("MLB1")
        qualquer = ml_client.buscar_menor_preco_concorrente("MLB1", mesma_prateleira=False)
        self.assertEqual(mesma, 50.0)
        self.assertEqual(qualquer, 22.0)

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_normalizar_concorrente_guarda_tipo(self, _en, mock_request):
        mock_request.side_effect = [
            _resp({"catalog_product_id": "CAT1", "listing_type_id": "gold_pro"}),
            _resp(
                {
                    "results": [
                        {
                            "id": "MLB9",
                            "seller_id": 9,
                            "title": "Kit",
                            "price": 22.0,
                            "listing_type_id": "gold_special",
                            "shipping": {"free_shipping": True, "logistic_type": "fulfillment"},
                        }
                    ]
                }
            ),
        ]
        det = ml_client.buscar_detalhes_concorrentes("MLB1")
        self.assertEqual(det[0]["listing_type_id"], "gold_special")
        self.assertEqual(det[0]["logistic_type"], "fulfillment")


def _resp(body: dict):
    from unittest.mock import MagicMock

    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    return r


if __name__ == "__main__":
    unittest.main()
