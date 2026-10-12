"""tests/test_pncp_client.py — circuit breaker e silêncio de erros PNCP."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestPncpBreaker(unittest.TestCase):
    def setUp(self):
        from integracoes.licitacao import pncp_client as pncp

        pncp.reset_breaker_para_teste()
        self.pncp = pncp

    def tearDown(self):
        self.pncp.reset_breaker_para_teste()

    def test_abre_breaker_apos_falhas(self):
        with patch.object(
            self.pncp,
            "_cfg",
            return_value=(5, 2, 60.0),
        ), patch.object(self.pncp._SESS, "get", side_effect=TimeoutError("read timeout")):
            self.assertEqual(self.pncp.buscar_propostas_abertas(codigo_modalidade=6), {})
            self.assertFalse(self.pncp.breaker_aberto())
            self.assertEqual(self.pncp.buscar_propostas_abertas(codigo_modalidade=6), {})
            self.assertTrue(self.pncp.breaker_aberto())

        with patch.object(self.pncp._SESS, "get") as mock_get:
            self.assertEqual(self.pncp.buscar_propostas_abertas(codigo_modalidade=6), {})
            mock_get.assert_not_called()

    def test_ok_zera_falhas(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data": []}
        with patch.object(self.pncp, "_cfg", return_value=(5, 3, 60.0)), patch.object(
            self.pncp._SESS, "get", side_effect=[TimeoutError("t"), resp]
        ):
            self.pncp.buscar_propostas_abertas(codigo_modalidade=6)
            self.assertFalse(self.pncp.breaker_aberto())
            out = self.pncp.buscar_propostas_abertas(codigo_modalidade=6)
            self.assertEqual(out, {"data": []})
            self.assertEqual(self.pncp.status_breaker()["falhas_seguidas"], 0)


if __name__ == "__main__":
    unittest.main()
