"""
tests/test_marketplace_keepalive.py — KA01–KA06
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import marketplace_keepalive


class TestMarketplaceKeepalive(unittest.TestCase):
    def test_KA01_registrar_acesso_cria_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "marketplace_keepalive.json"
            with patch.object(marketplace_keepalive, "STATE_FILE", state_path):
                marketplace_keepalive.registrar_acesso("shopee")
            self.assertTrue(state_path.is_file())
            data = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("shopee", data)

    def test_KA02_registrar_acesso_atualiza_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "marketplace_keepalive.json"
            with patch.object(marketplace_keepalive, "STATE_FILE", state_path):
                marketplace_keepalive.registrar_acesso("shopee")
                first = json.loads(state_path.read_text(encoding="utf-8"))["shopee"]
                marketplace_keepalive.registrar_acesso("shopee")
                second = json.loads(state_path.read_text(encoding="utf-8"))["shopee"]
            self.assertNotEqual(first, second)

    def test_KA03_dias_sem_acesso_nunca_acessado(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "marketplace_keepalive.json"
            with patch.object(marketplace_keepalive, "STATE_FILE", state_path):
                self.assertIsNone(marketplace_keepalive.dias_sem_acesso("shopee"))

    def test_KA04_dias_sem_acesso_hoje(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "marketplace_keepalive.json"
            with patch.object(marketplace_keepalive, "STATE_FILE", state_path):
                marketplace_keepalive.registrar_acesso("shopee")
                self.assertEqual(marketplace_keepalive.dias_sem_acesso("shopee"), 0)

    def test_KA05_dias_sem_acesso_acesso_antigo(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "logs" / "marketplace_keepalive.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
            state_path.write_text(json.dumps({"shopee": ts}, ensure_ascii=False), encoding="utf-8")
            with patch.object(marketplace_keepalive, "STATE_FILE", state_path):
                self.assertEqual(marketplace_keepalive.dias_sem_acesso("shopee"), 3)

    def test_KA06_registrar_acesso_cria_pasta_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "nao_existe" / "logs"
            state_path = nested / "marketplace_keepalive.json"
            with patch.object(marketplace_keepalive, "STATE_FILE", state_path):
                marketplace_keepalive.registrar_acesso("shopee")
            self.assertTrue(state_path.parent.is_dir())
            self.assertTrue(state_path.is_file())


if __name__ == "__main__":
    unittest.main()
