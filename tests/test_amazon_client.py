"""
tests/test_amazon_client.py — AZ01–AZ07
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.amazon import amazon_client


def _mock_resp(body: dict) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    return r


class TestAmazonClient(unittest.TestCase):
    @patch.object(amazon_client, "_enabled", return_value=False)
    def test_AZ01_listar_mensagens_nao_configurado(self, *_patches):
        self.assertEqual(amazon_client.listar_mensagens_nao_respondidas(), [])

    @patch.object(amazon_client, "request")
    @patch.object(amazon_client, "_enabled", return_value=True)
    def test_AZ02_listar_mensagens_sucesso(self, _mock_en, mock_request):
        mock_request.return_value = _mock_resp({"messages": [{"id": "m1", "text": "Olá"}]})
        msgs = amazon_client.listar_mensagens_nao_respondidas()
        self.assertEqual(msgs[0]["id"], "m1")

    @patch.object(amazon_client, "request", side_effect=Exception("boom"))
    @patch.object(amazon_client, "_enabled", return_value=True)
    def test_AZ03_listar_mensagens_excecao(self, *_patches):
        self.assertEqual(amazon_client.listar_mensagens_nao_respondidas(), [])

    @patch.object(amazon_client, "request")
    @patch.object(amazon_client, "_enabled", return_value=True)
    def test_AZ04_responder_mensagem_sucesso(self, _mock_en, mock_request):
        mock_request.return_value = _mock_resp({})
        self.assertTrue(amazon_client.responder_mensagem("thread1", "Obrigado!"))

    @patch.object(amazon_client, "request", side_effect=Exception("boom"))
    @patch.object(amazon_client, "_enabled", return_value=True)
    def test_AZ05_responder_mensagem_excecao(self, *_patches):
        self.assertFalse(amazon_client.responder_mensagem("thread1", "texto"))

    @patch.object(amazon_client, "dias_sem_acesso", return_value=0)
    @patch.object(amazon_client, "registrar_acesso")
    @patch.object(amazon_client, "listar_mensagens_nao_respondidas_detalhado", return_value=([], True))
    @patch.object(amazon_client, "_enabled", return_value=True)
    def test_AZ06_obter_saude_conta(self, *_patches):
        saude = amazon_client.obter_saude_conta()
        self.assertIn("configurado", saude)
        amazon_client.registrar_acesso.assert_called_once()

    @patch.object(amazon_client, "request")
    @patch.object(amazon_client, "_enabled", return_value=True)
    def test_AZ07_listar_pedidos_lista(self, _mock_en, mock_request):
        mock_request.return_value = _mock_resp({"payload": {"Orders": []}})
        self.assertIsInstance(amazon_client.listar_pedidos(), list)

    @patch("core.guardrails.bloqueio_escrita_global", return_value={"ok": False, "erro": "ROBO_PAUSAR_ESCRITA"})
    @patch.object(amazon_client, "request")
    @patch.object(amazon_client, "_enabled", return_value=True)
    def test_AZ08_atualizar_preco_bloqueado_kill_switch(self, mock_request, *_):
        self.assertFalse(amazon_client.atualizar_preco_item("SKU1", 19.9))
        mock_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
