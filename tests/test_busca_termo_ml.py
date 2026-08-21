"""
tests/test_busca_termo_ml.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.ml import busca_termo_ml, ml_client
from tests.http_fixtures import make_http_response


def _mock_resp(body: dict, status: int = 200) -> MagicMock:
    return make_http_response(status_code=status, json_body=body)


@pytest.mark.usefixtures("env_tokens")
class TestExtrairItemIdMl(unittest.TestCase):
    def test_url_produto(self):
        self.assertEqual(
            busca_termo_ml.extrair_item_id_ml(
                "https://produto.mercadolivre.com.br/MLB-123456789-kit-impala"
            ),
            "MLB123456789",
        )

    def test_id_direto(self):
        self.assertEqual(busca_termo_ml.extrair_item_id_ml("MLB9876543210"), "MLB9876543210")

    def test_vazio(self):
        self.assertIsNone(busca_termo_ml.extrair_item_id_ml(""))


@pytest.mark.usefixtures("env_tokens")
class TestExecutarBuscaTermo(unittest.TestCase):
    def test_api_ok_retorna_direto(self):
        item = {
            "id": "MLB2",
            "title": "Kit Impala",
            "price": 35,
            "seller": {"id": "888"},
            "shipping": {"free_shipping": True},
            "condition": "new",
            "sold_quantity": 5,
        }
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml"
        ) as mock_req, patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_SITES_SEARCH", True
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_PRODUCTS", False
        ):
            mock_req.return_value = _mock_resp({"results": [item]})
            out = busca_termo_ml.executar_busca_termo("kit impala", limite=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fonte_busca"], "api")

    def test_padrao_nao_chama_sites_search(self):
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml"
        ) as mock_req, patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_CATALOGO", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_BRAVE", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_DDG", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_CACHE", False
        ):
            mock_req.side_effect = [
                _mock_resp(
                    {
                        "results": [
                            {"id": "MLB41490081", "name": "Kit Impala"}
                        ]
                    }
                ),
                _mock_resp(
                    {
                        "id": "MLB41490081",
                        "name": "Kit Impala",
                        "date_created": "2024-10-04T03:32:02Z",
                    }
                ),
                _mock_resp(
                    {
                        "results": [
                            {
                                "item_id": "MLB1",
                                "seller_id": 888,
                                "price": 35.0,
                                "sold_quantity": 5,
                            }
                        ]
                    }
                ),
            ]
            out = busca_termo_ml.executar_busca_termo("kit impala", limite=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fonte_busca"], "products_api")
        urls = [str(c.args[1]) for c in mock_req.call_args_list]
        self.assertTrue(any("/products/search" in u for u in urls))
        self.assertFalse(any("/sites/" in u and "/search" in u for u in urls))

    def test_403_usa_fallback_ddg(self):
        item_body = {
            "id": "MLB123",
            "title": "Kit Impala 5 esmaltes",
            "price": 29.9,
            "seller": {"id": "888"},
            "shipping": {},
            "condition": "new",
            "sold_quantity": 12,
        }
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml"
        ) as mock_req, patch.object(
            ml_client, "listar_meus_anuncios", return_value=[]
        ), patch.object(
            ml_client, "buscar_detalhes_concorrentes", return_value=[]
        ), patch(
            "integracoes.ml.busca_termo_ml.ddg_buscar"
        ) as mock_ddg, patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_CATALOGO", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_PRODUCTS", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_BRAVE", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_SITES_SEARCH", True
        ):
            mock_req.side_effect = [
                _mock_resp({}, status=403),
                _mock_resp(item_body),
            ]
            mock_ddg.return_value = [
                {
                    "url": "https://produto.mercadolivre.com.br/MLB-123-kit",
                    "title": "Kit Impala",
                }
            ]
            out = busca_termo_ml.executar_busca_termo("esmalte impala kit", limite=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["item_id"], "MLB123")
        self.assertEqual(out[0]["fonte_busca"], "ddg")

    def test_403_incrementa_metrica_busca(self):
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml", return_value=_mock_resp({}, status=403)
        ), patch.object(ml_client, "listar_meus_anuncios", return_value=[]), patch(
            "integracoes.ml.busca_termo_ml.incrementar"
        ) as mock_inc, patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_CATALOGO", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_PRODUCTS", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_BRAVE", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_DDG", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_CACHE", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_SITES_SEARCH", True
        ):
            out = busca_termo_ml.executar_busca_termo("kit x", limite=3)
        self.assertEqual(out, [])
        mock_inc.assert_any_call("ml.busca.sites_search_403")

    def test_403_usa_fallback_products_api(self):
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml"
        ) as mock_req, patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_CATALOGO", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_BRAVE", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_DDG", False
        ):
            mock_req.side_effect = [
                _mock_resp(
                    {
                        "results": [
                            {"id": "MLB41490081", "name": "Kit 5 Esmaltes Impala Bailarina"}
                        ]
                    }
                ),  # products/search
                _mock_resp(
                    {
                        "id": "MLB41490081",
                        "name": "Kit 5 Esmaltes Impala Bailarina",
                        "date_created": "2024-10-04T03:32:02Z",
                    }
                ),  # products/{id}
                _mock_resp(
                    {
                        "results": [
                            {
                                "item_id": "MLB3948390421",
                                "seller_id": 1666381510,
                                "price": 30.99,
                                "sold_quantity": 50,
                            }
                        ]
                    }
                ),  # products/{id}/items
            ]
            out = busca_termo_ml.executar_busca_termo("kit 5 esmaltes impala bailarina", limite=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fonte_busca"], "products_api")
        self.assertEqual(out[0]["preco"], 30.99)
        self.assertEqual(out[0]["seller_id"], "1666381510")

    def test_fallback_catalogo(self):
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml"
        ) as mock_req, patch.object(
            ml_client,
            "listar_meus_anuncios",
            return_value=[{"item_id": "MLB_REF", "titulo": "kit anita esmalte"}],
        ), patch.object(
            ml_client,
            "buscar_detalhes_concorrentes",
            return_value=[
                {
                    "id": "MLB9",
                    "titulo": "Kit Anita esmalte",
                    "preco": 40.0,
                    "frete_gratis": True,
                    "condicao": "new",
                    "quantidade_vendida": 3,
                }
            ],
        ), patch.object(busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_DDG", False), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_BRAVE", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_PRODUCTS", False
        ):
            mock_req.return_value = _mock_resp({}, status=403)
            out = busca_termo_ml.executar_busca_termo(
                "kit anita",
                limite=5,
                item_id_referencia="MLB_REF",
            )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fonte_busca"], "catalogo")

    def test_fallback_cache_quando_tudo_vazio(self):
        from datetime import datetime, timezone

        cache = {
            "kit impala": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "resultados": [
                    {
                        "item_id": "MLB77",
                        "titulo": "Kit Impala",
                        "preco": 29.9,
                        "frete_gratis": False,
                        "condicao": "new",
                        "quantidade_vendida": 2,
                        "seller_id": "1",
                        "permalink": "",
                    }
                ],
            }
        }
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml"
        ) as mock_req, patch.object(ml_client, "listar_meus_anuncios", return_value=[]), patch.object(
            ml_client, "buscar_detalhes_concorrentes", return_value=[]
        ), patch.object(busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_DDG", False), patch.object(
            busca_termo_ml, "ler_json", return_value=cache
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_PRODUCTS", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_BRAVE", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_CATALOGO", False
        ):
            mock_req.return_value = _mock_resp({}, status=403)
            out = busca_termo_ml.executar_busca_termo("kit impala", limite=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fonte_busca"], "cache")

    def test_fallback_brave(self):
        item_body = {
            "id": "MLB555",
            "title": "Kit Impala esmalte manicure",
            "price": 31.9,
            "seller": {"id": "888"},
            "shipping": {},
            "condition": "new",
            "sold_quantity": 4,
        }
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            ml_client, "_request_ml"
        ) as mock_req, patch.object(ml_client, "listar_meus_anuncios", return_value=[]), patch.object(
            ml_client, "buscar_detalhes_concorrentes", return_value=[]
        ), patch.object(busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_DDG", False), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_PRODUCTS", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_CATALOGO", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_CACHE", False
        ), patch(
            "core.brave_search.request"
        ) as mock_http:
            mock_req.side_effect = [
                _mock_resp(item_body),
            ]
            mock_http.return_value = _mock_resp(
                {
                    "web": {
                        "results": [
                            {
                                "url": "https://produto.mercadolivre.com.br/MLB-555-kit",
                                "title": "Kit Impala",
                                "description": "esmalte",
                            }
                        ]
                    }
                }
            )
            with patch.object(busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_BRAVE", True):
                with patch("integracoes.ml.busca_externa_brave.BRAVE_SEARCH_API_KEY", "test-key"):
                    with patch(
                        "core.brave_search._cfg",
                        return_value=("test-key", 9999, 80.0, True),
                    ):
                        out = busca_termo_ml.executar_busca_termo("kit impala", limite=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fonte_busca"], "brave")


class TestTituloRelevante(unittest.TestCase):
    def test_exige_marca_quando_no_termo(self):
        self.assertTrue(
            busca_termo_ml._titulo_relevante(
                "kit 5 esmaltes impala bailarina",
                "Kit 5 Esmaltes Impala Bailarina Sortidos",
            )
        )
        self.assertFalse(
            busca_termo_ml._titulo_relevante(
                "kit 5 esmaltes impala bailarina",
                "Kit 5 Esmaltes Risqué Sortidos",
            )
        )

    def test_filtra_lista(self):
        rows = [
            {"titulo": "Kit Impala Bailarina", "preco": 30},
            {"titulo": "Cabo USB", "preco": 10},
        ]
        out = busca_termo_ml.filtrar_por_relevancia_titulo("kit impala bailarina", rows)
        self.assertEqual(len(out), 1)


@pytest.mark.usefixtures("env_tokens")
class TestCacheStaleHidrata(unittest.TestCase):
    def test_ttl_vencido_hidrata_ids(self):
        cache = {
            "kit impala": {
                "timestamp": "2026-07-10T16:53:36+00:00",
                "resultados": [
                    {
                        "item_id": "MLB3715746005",
                        "titulo": "Kit Impala",
                        "preco": 22.5,
                    }
                ],
            }
        }
        hidratado = [
            {
                "item_id": "MLB3715746005",
                "titulo": "Kit Impala",
                "preco": 24.9,
                "fonte_busca": "items_ids",
            }
        ]
        with patch.object(ml_client, "_enabled", return_value=True), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_PRODUCTS", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_CATALOGO", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_BRAVE", False
        ), patch.object(
            busca_termo_ml, "ML_BUSCA_TERMO_FALLBACK_DDG", False
        ), patch.object(
            busca_termo_ml, "ler_json", return_value=cache
        ), patch.object(
            ml_client, "hidratar_itens", return_value=hidratado
        ) as mock_hid:
            out = busca_termo_ml.executar_busca_termo("kit impala", limite=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["item_id"], "MLB3715746005")
        self.assertEqual(out[0]["preco"], 24.9)
        mock_hid.assert_called()


if __name__ == "__main__":
    unittest.main()
