"""
tests/test_cotacao_usd.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.cambio import cotacao_usd as cambio


class CotacaoUsdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hist = Path(self.tmp.name) / "cambio.json"

    def tearDown(self):
        self.tmp.cleanup()

    @patch("integracoes.cambio.cotacao_usd.request")
    def test_obter_cotacao_api(self, mock_req):
        mock_req.return_value = MagicMock(
            status_code=200,
            raise_for_status=MagicMock(),
            json=MagicMock(
                return_value={"USDBRL": {"bid": "5.42", "pctChange": "0.3", "high": "5.5", "low": "5.4"}}
            ),
        )
        with patch.object(cambio, "HISTORY_PATH", self.hist):
            out = cambio.obter_cotacao_usd()
        self.assertTrue(out["ok"])
        self.assertEqual(out["usd_brl"], 5.42)
        self.assertEqual(out["fonte"], "awesomeapi")

    @patch("integracoes.cambio.cotacao_usd.request", side_effect=RuntimeError("offline"))
    def test_fallback_quando_api_falha(self, _mock_req):
        with patch.object(cambio, "HISTORY_PATH", self.hist), patch.object(
            cambio, "CAMBIO_FALLBACK_USD_BRL", 5.5
        ):
            out = cambio.obter_cotacao_usd()
        self.assertTrue(out["ok"])
        self.assertEqual(out["fonte"], "fallback")


if __name__ == "__main__":
    unittest.main()
