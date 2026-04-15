import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Evita dependências externas para importação do cliente em ambiente mínimo de teste.
if "core.config" not in sys.modules:
    config_stub = types.ModuleType("core.config")
    config_stub.SHOPEE_ACCESS_TOKEN = "token"
    config_stub.SHOPEE_PARTNER_ID = "1"
    config_stub.SHOPEE_PARTNER_KEY = "key"
    config_stub.SHOPEE_SHOP_ID = "2"
    sys.modules["core.config"] = config_stub

if "core.http_client" not in sys.modules:
    http_stub = types.ModuleType("core.http_client")
    http_stub.request = lambda *_args, **_kwargs: None
    sys.modules["core.http_client"] = http_stub

if "core.marketplace_keepalive" not in sys.modules:
    keepalive_stub = types.ModuleType("core.marketplace_keepalive")
    keepalive_stub.registrar_acesso = lambda *_args, **_kwargs: None
    keepalive_stub.dias_sem_acesso = lambda *_args, **_kwargs: 0
    sys.modules["core.marketplace_keepalive"] = keepalive_stub

from integracoes.shopee import shopee_client


class ShopeeClientTests(unittest.TestCase):
    @staticmethod
    def _mock_response(body: dict) -> Mock:
        resp = Mock()
        resp.raise_for_status = Mock()
        resp.json.return_value = body
        return resp

    def test_tem_erro_api_detecta_erros_em_niveis_diferentes(self):
        self.assertTrue(shopee_client._tem_erro_api({"error": "invalid_signature"}))
        self.assertTrue(shopee_client._tem_erro_api({"response": {"error": "partial_failure"}}))
        self.assertTrue(shopee_client._tem_erro_api({"response": {"errors": [{"code": 1}]}}))
        self.assertTrue(shopee_client._tem_erro_api({"response": {"error_list": [{"code": 2}]}}))
        self.assertTrue(shopee_client._tem_erro_api({"response": {"failed_list": [{"code": 3}]}}))
        self.assertFalse(shopee_client._tem_erro_api({"error": "", "response": {"comment_list": []}}))

    @patch("integracoes.shopee.shopee_client.request")
    @patch("integracoes.shopee.shopee_client._enabled", return_value=True)
    def test_listar_perguntas_paginar_ate_proxima_pagina(self, _mock_enabled, mock_request):
        page1 = self._mock_response({
            "error": "",
            "response": {
                "comment_list": [{"comment_id": 1}],
                "next_cursor": "abc",
                "more": True,
            },
        })
        page2 = self._mock_response({
            "error": "",
            "response": {
                "comment_list": [{"comment_id": 2}],
                "more": False,
            },
        })

        mock_request.side_effect = [page1, page2]

        perguntas = shopee_client.listar_perguntas_nao_respondidas(page_size=10, max_pages=5)

        self.assertEqual(len(perguntas), 2)
        self.assertEqual(perguntas[0]["comment_id"], 1)
        self.assertEqual(perguntas[1]["comment_id"], 2)
        self.assertEqual(mock_request.call_count, 2)
        self.assertEqual(mock_request.call_args_list[0].kwargs["params"]["comment_status"], "UNREAD")
        self.assertEqual(mock_request.call_args_list[1].kwargs["params"]["cursor"], "abc")

    @patch("integracoes.shopee.shopee_client.request")
    @patch("integracoes.shopee.shopee_client._enabled", return_value=True)
    def test_listar_perguntas_limita_quantidade_de_paginas(self, _mock_enabled, mock_request):
        mock_request.side_effect = [
            self._mock_response({"error": "", "response": {"comment_list": [{"comment_id": 1}], "next_cursor": "a", "more": True}}),
            self._mock_response({"error": "", "response": {"comment_list": [{"comment_id": 2}], "next_cursor": "b", "more": True}}),
            self._mock_response({"error": "", "response": {"comment_list": [{"comment_id": 3}], "more": False}}),
        ]

        perguntas = shopee_client.listar_perguntas_nao_respondidas(page_size=10, max_pages=2)
        self.assertEqual([p["comment_id"] for p in perguntas], [1, 2])
        self.assertEqual(mock_request.call_count, 2)

    @patch("integracoes.shopee.shopee_client.request")
    @patch("integracoes.shopee.shopee_client._enabled", return_value=True)
    def test_listar_perguntas_retorna_vazio_quando_api_tem_erro(self, _mock_enabled, mock_request):
        mock_request.return_value = self._mock_response({"error": "bad_request", "response": {}})

        perguntas = shopee_client.listar_perguntas_nao_respondidas(page_size=10, max_pages=2)
        self.assertEqual(perguntas, [])

    @patch("integracoes.shopee.shopee_client._enabled", return_value=False)
    def test_listar_perguntas_retorna_vazio_quando_nao_configurado(self, _mock_enabled):
        perguntas = shopee_client.listar_perguntas_nao_respondidas()
        self.assertEqual(perguntas, [])

    @patch("integracoes.shopee.shopee_client.dias_sem_acesso", return_value=0)
    @patch("integracoes.shopee.shopee_client.registrar_acesso")
    @patch("integracoes.shopee.shopee_client._listar_perguntas_nao_respondidas_detalhado")
    @patch("integracoes.shopee.shopee_client._enabled", return_value=True)
    def test_obter_saude_conta_registra_acesso_so_quando_chamada_ok(
        self, _mock_enabled, mock_listar, mock_registrar, _mock_dias
    ):
        mock_listar.return_value = ([{"comment_id": 1}], True)
        out_ok = shopee_client.obter_saude_conta()
        self.assertTrue(out_ok["configurado"])
        self.assertEqual(out_ok["pendencias"], 1)
        mock_registrar.assert_called_once_with("shopee")

        mock_registrar.reset_mock()
        mock_listar.return_value = ([], False)
        out_fail = shopee_client.obter_saude_conta()
        self.assertTrue(out_fail["configurado"])
        self.assertEqual(out_fail["pendencias"], 0)
        mock_registrar.assert_not_called()

    @patch("integracoes.shopee.shopee_client._enabled", return_value=False)
    def test_obter_saude_conta_quando_nao_configurado(self, _mock_enabled):
        out = shopee_client.obter_saude_conta()
        self.assertFalse(out["configurado"])
        self.assertEqual(out["pendencias"], 0)

    @patch("integracoes.shopee.shopee_client.request")
    @patch("integracoes.shopee.shopee_client._enabled", return_value=True)
    def test_responder_pergunta_falha_quando_resposta_tem_erro(self, _mock_enabled, mock_request):
        mock_request.return_value = self._mock_response({"error": "", "response": {"errors": [{"code": 500}]}})

        ok = shopee_client.responder_pergunta(item_id=10, comment_id=20, texto="teste")
        self.assertFalse(ok)

    @patch("integracoes.shopee.shopee_client.request")
    @patch("integracoes.shopee.shopee_client._enabled", return_value=True)
    def test_responder_pergunta_sucesso(self, _mock_enabled, mock_request):
        mock_request.return_value = self._mock_response({"error": "", "response": {}})
        ok = shopee_client.responder_pergunta(item_id=10, comment_id=20, texto="teste")
        self.assertTrue(ok)

    @patch("integracoes.shopee.shopee_client.request")
    @patch("integracoes.shopee.shopee_client._enabled", return_value=True)
    def test_atualizar_preco_item_sem_model_id(self, _mock_enabled, mock_request):
        mock_request.return_value = self._mock_response({"error": "", "response": {}})
        ok = shopee_client.atualizar_preco_item(item_id=11, novo_preco=19.9)
        self.assertTrue(ok)

        payload = mock_request.call_args.kwargs["json"]
        self.assertEqual(payload["price_list"][0]["item_id"], 11)
        self.assertEqual(payload["price_list"][0]["original_price"], 19.9)
        self.assertNotIn("model_list", payload["price_list"][0])

    @patch("integracoes.shopee.shopee_client.request")
    @patch("integracoes.shopee.shopee_client._enabled", return_value=True)
    def test_atualizar_preco_item_com_model_id(self, _mock_enabled, mock_request):
        mock_request.return_value = self._mock_response({"error": "", "response": {}})
        ok = shopee_client.atualizar_preco_item(item_id=11, novo_preco=19.9, model_id=44)
        self.assertTrue(ok)

        payload = mock_request.call_args.kwargs["json"]
        self.assertEqual(payload["price_list"][0]["model_list"][0]["model_id"], 44)
        self.assertEqual(payload["price_list"][0]["model_list"][0]["original_price"], 19.9)

    @patch("integracoes.shopee.shopee_client.request")
    @patch("integracoes.shopee.shopee_client._enabled", return_value=True)
    def test_atualizar_estoque_item_sem_model_id(self, _mock_enabled, mock_request):
        mock_request.return_value = self._mock_response({"error": "", "response": {}})
        ok = shopee_client.atualizar_estoque_item(item_id=22, novo_estoque=-3)
        self.assertTrue(ok)

        payload = mock_request.call_args.kwargs["json"]
        self.assertEqual(payload["stock_list"][0]["item_id"], 22)
        self.assertEqual(payload["stock_list"][0]["normal_stock"], 0)
        self.assertNotIn("model_list", payload["stock_list"][0])

    @patch("integracoes.shopee.shopee_client.request")
    @patch("integracoes.shopee.shopee_client._enabled", return_value=True)
    def test_atualizar_estoque_item_com_model_id(self, _mock_enabled, mock_request):
        mock_request.return_value = self._mock_response({"error": "", "response": {}})
        ok = shopee_client.atualizar_estoque_item(item_id=22, novo_estoque=7, model_id=55)
        self.assertTrue(ok)

        payload = mock_request.call_args.kwargs["json"]
        self.assertEqual(payload["stock_list"][0]["model_list"][0]["model_id"], 55)
        self.assertEqual(payload["stock_list"][0]["model_list"][0]["normal_stock"], 7)

    @patch("integracoes.shopee.shopee_client._enabled", return_value=False)
    def test_atualizacoes_retorna_false_quando_nao_configurado(self, _mock_enabled):
        self.assertFalse(shopee_client.atualizar_preco_item(item_id=10, novo_preco=10.0))
        self.assertFalse(shopee_client.atualizar_estoque_item(item_id=10, novo_estoque=5))


if __name__ == "__main__":
    unittest.main()
