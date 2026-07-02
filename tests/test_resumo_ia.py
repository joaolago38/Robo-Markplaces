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

    @patch("core.resumo_ia.perguntar", return_value="ok")
    @patch("core.resumo_ia.cfg.ANTHROPIC_API_KEY", "sk")
    def test_guardrail_no_prompt(self, mock_perguntar):
        sintetizar_claude("analise", {"x": 1}, "fb", max_tokens=100)
        prompt = mock_perguntar.call_args[0][0]
        self.assertIn(GUARDRAIL, prompt)


if __name__ == "__main__":
    unittest.main()
