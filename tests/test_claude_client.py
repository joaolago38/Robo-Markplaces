"""
tests/test_claude_client.py — CC01–CC05
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import claude_client


def _mock_resp(body: dict) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    return r


class TestClaudePerguntar(unittest.TestCase):
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "")
    def test_CC01_pergunta_sem_api_key(self, *_patches):
        out = claude_client.perguntar("oi")
        self.assertTrue("API" in out or "configurada" in out.lower())

    @patch.object(claude_client, "request")
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC02_pergunta_retorna_texto_resposta(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp({"content": [{"text": "resposta IA"}]})
        self.assertEqual(claude_client.perguntar("pergunta"), "resposta IA")

    @patch.object(claude_client, "request", side_effect=Exception("timeout"))
    @patch.object(claude_client, "ANTHROPIC_API_KEY", "k")
    def test_CC03_pergunta_fallback_em_excecao(self, *_patches):
        out = claude_client.perguntar("teste")
        self.assertTrue(out.startswith("⚠️"))


class TestClaudeResponderGerar(unittest.TestCase):
    @patch.object(claude_client, "perguntar", return_value="ok")
    def test_CC04_responder_chat_prompt_contem_canal_e_produto(self, mock_perguntar):
        produto = {"nome": "Kit 12", "preco": 59.90, "estoque": 50}
        claude_client.responder_chat("Qual a composição química do esmalte?", produto, "shopee")
        prompt = mock_perguntar.call_args[0][0]
        self.assertIn("shopee", prompt.lower())
        self.assertIn("Kit 12", prompt)
        self.assertIn("59.90", prompt)

    @patch.object(claude_client, "perguntar", return_value="post")
    def test_CC05_gerar_post_prompt_contem_canal_e_nome(self, mock_perguntar):
        produto = {"nome": "Kit Impala", "preco": 49.90}
        claude_client.gerar_post(produto, "instagram")
        prompt = mock_perguntar.call_args[0][0]
        self.assertIn("instagram", prompt.lower())
        self.assertIn("Kit Impala", prompt)


if __name__ == "__main__":
    unittest.main()
