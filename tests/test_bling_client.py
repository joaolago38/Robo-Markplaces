"""
tests/test_bling_client.py — BL01–BL08
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.bling import bling_client


def _mock_resp(body: dict) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    return r


class TestBlingBuscar(unittest.TestCase):
    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request")
    def test_BL01_buscar_produto_normalizado(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp(
            {
                "data": [
                    {
                        "codigo": "SKU1",
                        "nome": "Kit",
                        "preco": 59.9,
                        "estoqueAtual": 100,
                        "ncm": "33041000",
                    }
                ]
            }
        )
        produto = bling_client.buscar_produto("SKU1")
        self.assertEqual(produto["sku"], "SKU1")
        self.assertEqual(produto["preco"], 59.9)
        self.assertEqual(produto["estoque"], 100)

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request")
    def test_BL02_buscar_produto_data_vazia(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"data": []})
        self.assertIsNone(bling_client.buscar_produto("SKU_INEXISTENTE"))

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request", side_effect=Exception("timeout"))
    def test_BL03_buscar_produto_none_em_rede(self, *_patches):
        self.assertIsNone(bling_client.buscar_produto("SKU1"))


class TestBlingListar(unittest.TestCase):
    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request")
    def test_BL04_listar_produtos_normalizado(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp(
            {
                "data": [
                    {"codigo": "A", "nome": "Kit A", "preco": 10.0, "estoqueAtual": 50},
                    {"codigo": "B", "nome": "Kit B", "preco": 20.0, "estoqueAtual": 5},
                ]
            }
        )
        mock_request.return_value.status_code = 200
        produtos = bling_client.listar_produtos()
        self.assertEqual(len(produtos), 2)
        self.assertEqual(produtos[0]["sku"], "A")

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request")
    def test_BL04b_listar_produtos_403_retorna_vazio(self, mock_request, *_patches):
        r403 = MagicMock()
        r403.status_code = 403
        r403.text = "Forbidden"
        mock_request.return_value = r403
        self.assertEqual(bling_client.listar_produtos(), [])

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request", side_effect=Exception("boom"))
    def test_BL05_listar_produtos_vazio_em_excecao(self, *_patches):
        self.assertEqual(bling_client.listar_produtos(), [])

    @patch.object(bling_client, "_request_bling")
    def test_BL05b_probe_403_sem_permissao(self, mock_req):
        r403 = MagicMock()
        r403.status_code = 403
        r403.text = "Forbidden"
        mock_req.return_value = r403
        out = bling_client.probe_produtos()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], 403)
        self.assertIn("escopo", out["msg"])


class TestBlingEstoquesNfe(unittest.TestCase):
    @patch.object(bling_client, "listar_produtos")
    def test_BL06_estoques_criticos_filtra_limite(self, mock_listar):
        mock_listar.return_value = [
            {"sku": "A", "estoque": 5},
            {"sku": "B", "estoque": 50},
            {"sku": "C", "estoque": 20},
        ]
        crit = bling_client.estoques_criticos(limite=20)
        self.assertEqual(len(crit), 2)
        skus = {p["sku"] for p in crit}
        self.assertEqual(skus, {"A", "C"})

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request")
    def test_BL07_criar_nfe_ok(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"data": {"id": 123, "numero": "001"}})
        resultado = bling_client.criar_nfe({"naturezaOperacao": "Venda", "itens": []})
        self.assertTrue(resultado["ok"])

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request", side_effect=Exception("timeout"))
    def test_BL08_criar_nfe_ok_false_em_excecao(self, *_patches):
        resultado = bling_client.criar_nfe({})
        self.assertFalse(resultado["ok"])
        self.assertIn("erro", resultado)


if __name__ == "__main__":
    unittest.main()
