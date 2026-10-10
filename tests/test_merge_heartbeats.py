"""O save do cache de saúde não pode republicar um heartbeat mais velho."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / ".github" / "actions" / "saude-heartbeats"),
)

import merge_heartbeats as hb  # noqa: E402


class MergeHeartbeatsTests(unittest.TestCase):
    def test_vigia_propria_tolera_atraso_do_cron(self):
        fontes = json.loads(
            (Path(__file__).resolve().parent.parent / "catalogo" / "datadog_vigia_fontes.json").read_text(
                encoding="utf-8"
            )
        )
        vigia = next(f for f in fontes if f.get("id") == "vigia_datadog")
        self.assertGreaterEqual(float(vigia["max_horas"]), 12)

    def test_mescla_fica_com_o_timestamp_mais_novo(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            job = raiz / "job"
            cache = raiz / "cache"
            rel = "logs/relatorio_estrategia_ml_ultima.json"
            (job / "logs").mkdir(parents=True)
            (cache / "logs").mkdir(parents=True)
            (job / rel).write_text(
                json.dumps({"timestamp": "2026-09-28T18:32:38+00:00", "ok": True}),
                encoding="utf-8",
            )
            (cache / rel).write_text(
                json.dumps({"timestamp": "2026-09-21T16:58:39+00:00", "ok": True}),
                encoding="utf-8",
            )
            escolhidos = hb.mesclar(job, cache, [rel])
            self.assertEqual(escolhidos, [rel])
            gravado = json.loads((cache / rel).read_text(encoding="utf-8"))
            self.assertTrue(gravado["timestamp"].startswith("2026-09-28"))

    def test_cache_mais_novo_nao_e_apagado_pelo_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            job = raiz / "job"
            cache = raiz / "cache"
            rel = "logs/filamentos_batalha_ultima.json"
            (job / "logs").mkdir(parents=True)
            (cache / "logs").mkdir(parents=True)
            (job / rel).write_text(
                json.dumps({"timestamp": "2026-08-01T00:00:00+00:00"}),
                encoding="utf-8",
            )
            (cache / rel).write_text(
                json.dumps({"timestamp": "2026-10-10T12:00:00+00:00"}),
                encoding="utf-8",
            )
            hb.mesclar(job, cache, [rel])
            gravado = json.loads((cache / rel).read_text(encoding="utf-8"))
            self.assertTrue(gravado["timestamp"].startswith("2026-10-10"))


if __name__ == "__main__":
    unittest.main()
