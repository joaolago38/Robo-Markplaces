"""
tests/test_orquestrador_runners.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.orquestrador import runners


class TestOrquestradorRunners(unittest.TestCase):
    @patch.object(runners, "_carregar_script")
    def test_renovar_tokens_ok(self, mock_carregar):
        mock_carregar.return_value = MagicMock(main=lambda: 0)
        out = runners.executar_renovar_tokens()
        self.assertTrue(out["ok"])

    @patch.object(runners, "_carregar_script")
    def test_renovar_tokens_falha(self, mock_carregar):
        mock_carregar.return_value = MagicMock(main=lambda: 1)
        out = runners.executar_renovar_tokens()
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
