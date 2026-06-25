"""
tests/test_preencher_item_id_ml.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "preencher_item_id_ml",
    os.path.join(ROOT, "scripts", "preencher_item_id_ml.py"),
)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

_CATALOGO = [
    {
        "sku": "SKU-A",
        "nome": "Kit A",
        "canais": {
            "mercadolivre": {
                "ativo": True,
                "item_id": "MLB_PREENCHER",
                "titulo_anuncio": "Kit A Impala",
            }
        },
    }
]

_ANUNCIOS = [
    {"item_id": "MLB111", "titulo": "Kit A Impala", "preco": 44.9, "sku": "SKU-A", "status": "active"},
]


class TestPreencherItemId(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.catalogo_path = Path(self.tmp.name) / "produtos.json"
        self.catalogo_path.write_text(json.dumps(_CATALOGO), encoding="utf-8")
        self._orig_path = script.CATALOGO_PATH
        script.CATALOGO_PATH = self.catalogo_path

    def tearDown(self):
        script.CATALOGO_PATH = self._orig_path
        self.tmp.cleanup()

    @patch("integracoes.ml.ml_client.listar_meus_anuncios")
    def test_dry_run_match_exato(self, mock_listar):
        mock_listar.return_value = _ANUNCIOS
        out = script.executar(aplicar=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_pendentes"], 1)
        self.assertEqual(out["resultados"][0]["tipo_match"], "EXATO")
        data = json.loads(self.catalogo_path.read_text(encoding="utf-8"))
        self.assertEqual(data[0]["canais"]["mercadolivre"]["item_id"], "MLB_PREENCHER")

    @patch("integracoes.ml.ml_client.listar_meus_anuncios")
    def test_aplicar_match_exato(self, mock_listar):
        mock_listar.return_value = _ANUNCIOS
        out = script.executar(aplicar=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_aplicados"], 1)
        data = json.loads(self.catalogo_path.read_text(encoding="utf-8"))
        self.assertEqual(data[0]["canais"]["mercadolivre"]["item_id"], "MLB111")

    @patch("integracoes.ml.ml_client.listar_meus_anuncios")
    def test_provavel_nao_aplica_sem_flag(self, mock_listar):
        catalogo = [
            {
                "sku": "SKU-A",
                "nome": "Kit A Impala Premium Edition",
                "canais": {
                    "mercadolivre": {
                        "ativo": True,
                        "item_id": "MLB_PREENCHER",
                        "titulo_anuncio": "Kit A Impala Premium Edition",
                    }
                },
            }
        ]
        self.catalogo_path.write_text(json.dumps(catalogo), encoding="utf-8")
        anuncios = [
            {
                "item_id": "MLB222",
                "titulo": "Kit A Impala Premium Edition 2024",
                "preco": 40,
                "sku": "OUTRO",
                "status": "active",
            }
        ]
        mock_listar.return_value = anuncios
        out = script.executar(aplicar=True, incluir_provaveis=False)
        self.assertEqual(out["total_aplicados"], 0)
        self.assertEqual(out["resultados"][0]["tipo_match"], "PROVÁVEL")


if __name__ == "__main__":
    unittest.main()
