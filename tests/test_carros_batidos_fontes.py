"""
tests/test_carros_batidos_fontes.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.veiculos import carros_batidos_fontes as cbf


class TestCarrosBatidosFontes(unittest.TestCase):
    def test_carregar_fontes_ativas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caminho = root / "fontes.json"
            caminho.write_text(
                json.dumps(
                    [
                        {"id": "a", "ativo": True, "nome": "A"},
                        {"id": "b", "ativo": False, "nome": "B"},
                    ]
                ),
                encoding="utf-8",
            )
            with patch.object(cbf, "ROOT", root):
                fontes = cbf.carregar_fontes("fontes.json")
            self.assertEqual(len(fontes), 1)
            self.assertEqual(fontes[0]["id"], "a")


if __name__ == "__main__":
    unittest.main()
