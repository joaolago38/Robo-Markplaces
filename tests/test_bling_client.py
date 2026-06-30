"""
tests/test_bling_client.py — BL01–BL20+
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.http_fixtures import make_http_response

from integracoes.bling import bling_client


def _mock_resp(body: dict, status: int = 200) -> MagicMock:
    return make_http_response(status_code=status, json_body=body, text=str(body))


class TestHelpers(unittest.TestCase):
    def test_to_float_invalido_usa_default(self):
        self.assertEqual(bling_client._to_float("x", 3.5), 3.5)

    def test_to_int_invalido_usa_default(self):
        self.assertEqual(bling_client._to_int(None, 9), 9)

    def test_extrair_estoque_saldo_virtual(self):
        self.assertEqual(bling_client._extrair_estoque({"saldoVirtualTotal": 12}), 12)

    def test_extrair_estoque_saldo_fisico(self):
        self.assertEqual(bling_client._extrair_estoque({"saldoFisicoTotal": 7}), 7)

    def test_extrair_estoque_aninhado(self):
        self.assertEqual(
            bling_client._extrair_estoque({"estoque": {"saldoVirtualTotal": 3}}),
            3,
        )

    def test_extrair_estoque_ausente_retorna_none(self):
        self.assertIsNone(bling_client._extrair_estoque({"nome": "Kit"}))

    def test_normalizar_produto_fallback_sku_id(self):
        p = bling_client._normalizar_produto(
            {"id": 99, "nome": "X", "imagemURL": "http://img", "preco": "10"}
        )
        self.assertEqual(p["sku"], "99")
        self.assertEqual(p["codigo"], "99")
        self.assertEqual(p["imagens"], ["http://img"])
        self.assertIsNone(p["estoque"])

    def test_normalizar_produto_imagens_invalidas(self):
        p = bling_client._normalizar_produto({"codigo": "A", "imagens": 123})
        self.assertEqual(p["imagens"], [])


class TestRequestBling(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _http(self, mock_http):
        self.mock_http = mock_http

    @patch.object(bling_client.token_manager, "get_token_bling", return_value="novo_tok")
    def test_renova_token_em_401(self, _mock_token):
        r401 = make_http_response(status_code=401)
        r200 = make_http_response(status_code=200)
        self.mock_http.side_effect = [r401, r200]
        out = bling_client._request_bling("GET", "http://x")
        self.assertEqual(out.status_code, 200)
        self.assertEqual(self.mock_http.call_count, 2)


class TestProbeProdutos(unittest.TestCase):
    @patch.object(bling_client, "_request_bling")
    def test_probe_200_ok(self, mock_req):
        mock_req.return_value = _mock_resp({"data": [{"codigo": "A"}]}, 200)
        out = bling_client.probe_produtos()
        self.assertTrue(out["ok"])
        self.assertEqual(out["amostra"], 1)

    @patch.object(bling_client, "_request_bling")
    def test_probe_401(self, mock_req):
        mock_req.return_value = _mock_resp({}, 401)
        out = bling_client.probe_produtos()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], 401)

    @patch.object(bling_client, "_request_bling")
    def test_probe_403(self, mock_req):
        mock_req.return_value = _mock_resp({}, 403)
        out = bling_client.probe_produtos()
        self.assertFalse(out["ok"])
        self.assertIn("escopo", out["msg"])

    @patch.object(bling_client, "_request_bling")
    def test_probe_outro_status_com_json(self, mock_req):
        mock_req.return_value = _mock_resp({"error": "limite"}, 429)
        out = bling_client.probe_produtos()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], 429)

    @patch.object(bling_client, "_request_bling")
    def test_probe_json_invalido(self, mock_req):
        r = MagicMock(status_code=500, text="html erro")
        r.json.side_effect = ValueError("bad json")
        mock_req.return_value = r
        out = bling_client.probe_produtos()
        self.assertIn("html", out["msg"])

    @patch.object(bling_client, "_request_bling", side_effect=ConnectionError("rede"))
    def test_probe_excecao_rede(self, *_):
        out = bling_client.probe_produtos()
        self.assertEqual(out["status"], 0)
        self.assertIn("rede", out["msg"])


@pytest.mark.usefixtures("env_tokens")
class TestBlingBuscar(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _http(self, mock_http):
        self.mock_http = mock_http

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    def test_BL01_buscar_produto_normalizado(self):
        self.mock_http.return_value = _mock_resp(
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
    def test_BL02_buscar_produto_data_vazia(self):
        self.mock_http.return_value = _mock_resp({"data": []})
        self.assertIsNone(bling_client.buscar_produto("SKU_INEXISTENTE"))

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    def test_BL03_buscar_produto_none_em_rede(self):
        self.mock_http.side_effect = Exception("timeout")
        self.assertIsNone(bling_client.buscar_produto("SKU1"))

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request")
    def test_buscar_produto_json_invalido(self, mock_request, *_):
        r = _mock_resp({})
        r.json.side_effect = ValueError("json")
        mock_request.return_value = r
        self.assertIsNone(bling_client.buscar_produto("SKU1"))


class TestBlingListar(unittest.TestCase):
    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request")
    def test_BL04_listar_produtos_normalizado(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp(
            {
                "data": [
                    {"codigo": "A", "nome": "Kit A", "preco": 10.0, "estoqueAtual": 50},
                    {"codigo": "B", "nome": "Kit B", "preco": 20.0, "saldoVirtualTotal": 5},
                ]
            }
        )
        produtos = bling_client.listar_produtos()
        self.assertEqual(len(produtos), 2)
        self.assertEqual(produtos[0]["sku"], "A")
        self.assertEqual(produtos[1]["estoque"], 5)

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request")
    def test_BL04b_listar_produtos_403_retorna_vazio(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({}, 403)
        self.assertEqual(bling_client.listar_produtos(), [])

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request", side_effect=Exception("boom"))
    def test_BL05_listar_produtos_vazio_em_excecao(self, *_patches):
        self.assertEqual(bling_client.listar_produtos(), [])

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request")
    def test_listar_produtos_json_invalido(self, mock_request, *_):
        r = _mock_resp({})
        r.json.side_effect = ValueError("json")
        mock_request.return_value = r
        self.assertEqual(bling_client.listar_produtos(), [])


class TestBlingEstoquesNfe(unittest.TestCase):
    @patch.object(bling_client, "listar_produtos")
    def test_BL06_estoques_criticos_filtra_limite(self, mock_listar):
        mock_listar.return_value = [
            {"sku": "A", "estoque": 5},
            {"sku": "B", "estoque": 50},
            {"sku": "C", "estoque": 20},
            {"sku": "D", "estoque": None},
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

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "")
    def test_criar_nfe_sem_token(self):
        out = bling_client.criar_nfe({})
        self.assertFalse(out["ok"])
        self.assertIn("BLING_ACCESS_TOKEN", out["erro"])

    @patch.object(bling_client, "BLING_ACCESS_TOKEN", "t")
    @patch.object(bling_client, "request", side_effect=Exception("timeout"))
    def test_BL08_criar_nfe_ok_false_em_excecao(self, *_patches):
        resultado = bling_client.criar_nfe({})
        self.assertFalse(resultado["ok"])
        self.assertIn("erro", resultado)


class TestBlingNcm(unittest.TestCase):
    def test_atualizar_ncm_invalido(self):
        out = bling_client.atualizar_ncm_produto(1, "123")
        self.assertFalse(out["ok"])
        self.assertIn("NCM inválido", out["erro"])

    @patch.object(bling_client, "obter_produto_completo", return_value={})
    def test_atualizar_ncm_produto_nao_encontrado(self, *_):
        out = bling_client.atualizar_ncm_produto(1, "33041000")
        self.assertFalse(out["ok"])
        self.assertIn("não encontrado", out["erro"])

    @patch.object(bling_client, "_request_bling")
    @patch.object(bling_client, "obter_produto_completo", return_value={"nome": "Kit"})
    def test_atualizar_ncm_sucesso(self, mock_get, mock_req):
        mock_req.return_value = _mock_resp({"data": {}})
        out = bling_client.atualizar_ncm_produto(10, "33.041.000")
        self.assertTrue(out["ok"])
        self.assertEqual(out["ncm"], "33041000")
        mock_get.assert_called_once_with(10)

    @patch.object(bling_client, "obter_produto_completo", side_effect=RuntimeError("api"))
    def test_atualizar_ncm_excecao(self, *_):
        out = bling_client.atualizar_ncm_produto(1, "33041000")
        self.assertFalse(out["ok"])

    @patch.object(bling_client, "_buscar_produto_raw", return_value=None)
    def test_definir_ncm_sku_nao_encontrado(self, *_):
        out = bling_client.definir_ncm_por_sku("SKU-X", "33041000")
        self.assertFalse(out["ok"])
        self.assertIn("não encontrado", out["erro"])

    @patch.object(bling_client, "_buscar_produto_raw", side_effect=RuntimeError("falha"))
    def test_definir_ncm_erro_busca(self, *_):
        out = bling_client.definir_ncm_por_sku("SKU-X", "33041000")
        self.assertFalse(out["ok"])
        self.assertEqual(out["sku"], "SKU-X")

    @patch.object(bling_client, "atualizar_ncm_produto", return_value={"ok": True, "ncm": "33041000"})
    @patch.object(bling_client, "_buscar_produto_raw", return_value={"id": 55})
    def test_definir_ncm_por_sku_sucesso(self, *_):
        out = bling_client.definir_ncm_por_sku("SKU-1", "33041000")
        self.assertTrue(out["ok"])
        self.assertEqual(out["sku"], "SKU-1")

    @patch.object(bling_client, "request")
    def test_buscar_produto_raw_e_obter_completo(self, mock_request):
        mock_request.return_value = _mock_resp({"data": [{"id": 7, "codigo": "X"}]})
        raw = bling_client._buscar_produto_raw("X")
        self.assertEqual(raw["id"], 7)
        mock_request.return_value = _mock_resp({"data": {"id": 7, "nome": "Kit"}})
        completo = bling_client.obter_produto_completo(7)
        self.assertEqual(completo["nome"], "Kit")


class TestBuscarNfePorPedido(unittest.TestCase):
    @patch.object(bling_client, "_request_bling")
    def test_encontra_nfe_existente(self, mock_req):
        data_emissao_recente = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
        mock_req.return_value = _mock_resp(
            {
                "data": [
                    {"numeroPedidoLoja": "OUTRO", "id": 1},
                    {"numeroPedidoLoja": "PED-1", "id": 42, "dataEmissao": data_emissao_recente},
                ]
            }
        )
        out = bling_client.buscar_nfe_por_pedido("PED-1")
        self.assertEqual(out["id"], 42)

    @patch.object(bling_client, "_request_bling")
    def test_nao_encontra_lista_vazia(self, mock_req):
        mock_req.return_value = _mock_resp({"data": []})
        self.assertIsNone(bling_client.buscar_nfe_por_pedido("PED-404"))

    @patch.object(bling_client, "_request_bling", side_effect=RuntimeError("rede"))
    def test_erro_rede_levanta_nfe_verificacao_indisponivel(self, *_):
        with self.assertRaises(bling_client.NfeVerificacaoIndisponivel):
            bling_client.buscar_nfe_por_pedido("PED-ERR")


if __name__ == "__main__":
    unittest.main()
