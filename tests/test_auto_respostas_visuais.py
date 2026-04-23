import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.auto_respostas_visuais import _gerar_resposta_visual

class AutoRespostasVisuaisTests(unittest.TestCase):
    @patch("agentes.auto_respostas_visuais.perguntar")
    def test_gera_prompt_com_fotos(self, mock_perguntar):
        mock_perguntar.return_value = "Resposta teste"
        produto = {"nome": "Esmalte", "preco": 9.9, "estoque": 10, "descricao": "Vermelho", "imagens": ["https://img1"]}
        out = _gerar_resposta_visual("Qual o tom?", produto, "mercadolivre")
        self.assertEqual(out, "Resposta teste")
        args, kwargs = mock_perguntar.call_args
        self.assertIn("Fotos publicadas do produto", args[0])
        self.assertIn("https://img1", args[0])
        self.assertEqual(kwargs["max_tokens"], 220)


if __name__ == "__main__":
    unittest.main()
