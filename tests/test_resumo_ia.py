"""tests/test_resumo_ia.py"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.resumo_ia import GUARDRAIL, sintetizar_claude


class TestResumoIa(unittest.TestCase):
    @patch("core.resumo_ia.cfg.ANTHROPIC_API_KEY", "")
    def test_sem_api_key_retorna_fallback(self):
        self.assertEqual(sintetizar_claude("prompt", {"a": 1}, "fb"), "fb")

    @patch("core.resumo_ia.cfg.ANTHROPIC_API_KEY", "")
    def test_somente_ia_sem_key_nao_mascara_fallback(self):
        self.assertEqual(sintetizar_claude("prompt", {"a": 1}, "fb", somente_ia=True), "")

    @patch("core.resumo_ia.perguntar", return_value="ok")
    @patch("core.resumo_ia.cfg.ANTHROPIC_API_KEY", "sk")
    def test_guardrail_no_prompt(self, mock_perguntar):
        ctx = {"x": 1, "detalhe": "contexto longo o suficiente para passar o mínimo de chars"}
        sintetizar_claude("analise", ctx, "fb", max_tokens=100, origem="teste.resumo")
        prompt = mock_perguntar.call_args[0][0]
        self.assertIn(GUARDRAIL, prompt)
        self.assertEqual(mock_perguntar.call_args.kwargs.get("origem"), "teste.resumo")

    @patch("core.resumo_ia.perguntar")
    @patch("core.resumo_ia.cfg.ANTHROPIC_API_KEY", "sk")
    def test_contexto_curto_nao_chama_api(self, mock_perguntar):
        out = sintetizar_claude("analise", {"a": 1}, "fb")
        self.assertEqual(out, "fb")
        mock_perguntar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
