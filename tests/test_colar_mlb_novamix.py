"""
tests/test_colar_mlb_novamix.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from tests._stdout_utf8 import capturar_stdout_utf8

_spec = importlib.util.spec_from_file_location(
    "colar_mlb_novamix",
    os.path.join(ROOT, "scripts", "colar_mlb_novamix.py"),
)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

_CATALOGO = [
    {
        "id": "kit3-mimo-carmed",
        "item_ids": [],
    },
    {
        "id": "loja-novamix-comercial",
        "seller_id": "1666381510",
        "item_ids": [],
    },
]


class TestColarMlbNovamix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.catalogo_path = Path(self.tmp.name) / "concorrentes_monitorados.json"
        self.catalogo_path.write_text(json.dumps(_CATALOGO), encoding="utf-8")
        self.cache_path = Path(self.tmp.name) / "cache.json"
        self._orig_cat = script.CATALOGO_PATH
        self._orig_cache = script.CACHE_PATH
        script.CATALOGO_PATH = self.catalogo_path
        script.CACHE_PATH = self.cache_path

    def tearDown(self):
        script.CATALOGO_PATH = self._orig_cat
        script.CACHE_PATH = self._orig_cache
        self.tmp.cleanup()

    def test_normaliza_url_e_placeholder(self):
        ids = script.normalizar_item_ids(
            [
                "https://produto.mercadolivre.com.br/MLB-3948390421",
                "MLB_PREENCHER",
                "MLB3948390421",
                "lixo",
            ]
        )
        self.assertEqual(ids, ["MLB3948390421"])

    def test_extrai_so_seller_novamix_do_cache(self):
        self.cache_path.write_text(
            json.dumps(
                {
                    "kit": {
                        "resultados": [
                            {"item_id": "MLB3948390421", "seller_id": "1666381510"},
                            {"item_id": "MLB1111111111", "seller_id": "999"},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(script.extrair_ids_do_cache(self.cache_path), ["MLB3948390421"])

    def test_dry_run_nao_grava(self):
        with capturar_stdout_utf8():
            out = script.executar(["MLB3948390421"], aplicar=False, caminho=self.catalogo_path)
        self.assertTrue(out["ok"])
        self.assertTrue(out["dry_run"])
        self.assertFalse(out["aplicado"])
        data = json.loads(self.catalogo_path.read_text(encoding="utf-8"))
        self.assertEqual(data[1]["item_ids"], [])

    def test_aplicar_mescla_ids(self):
        with capturar_stdout_utf8():
            script.executar(["MLB3948390421"], aplicar=True, caminho=self.catalogo_path)
            out = script.executar(["MLB5192919860"], aplicar=True, caminho=self.catalogo_path)
        self.assertTrue(out["aplicado"])
        data = json.loads(self.catalogo_path.read_text(encoding="utf-8"))
        self.assertEqual(data[1]["item_ids"], ["MLB3948390421", "MLB5192919860"])
        self.assertEqual(data[0]["item_ids"], [])

    def test_do_cache_aplicar(self):
        self.cache_path.write_text(
            json.dumps(
                {
                    "kit": {
                        "resultados": [
                            {"item_id": "MLB3607560029", "seller_id": "1666381510"},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        with capturar_stdout_utf8():
            out = script.executar(
                do_cache=True,
                aplicar=True,
                caminho=self.catalogo_path,
                cache_path=self.cache_path,
            )
        self.assertEqual(out["item_ids"], ["MLB3607560029"])
        data = json.loads(self.catalogo_path.read_text(encoding="utf-8"))
        self.assertEqual(data[1]["item_ids"], ["MLB3607560029"])
