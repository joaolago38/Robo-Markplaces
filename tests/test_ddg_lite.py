"""
tests/test_ddg_lite.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import ddg_lite as ddg


class TestDdgLite(unittest.TestCase):
    def setUp(self):
        ddg.reset_circuit_breaker()

    @patch.object(ddg.time, "sleep")
    @patch.object(ddg, "request")
    def test_circuit_breaker_apos_varias_403(self, mock_request, _sleep):
        from core.config import DDG_FALHAS_403_PARA_BREAKER

        bloqueado = MagicMock()
        bloqueado.status_code = 403
        mock_request.return_value = bloqueado
        for _ in range(DDG_FALHAS_403_PARA_BREAKER):
            ddg.buscar("teste", contexto="teste")
        self.assertEqual(ddg.buscar("outra", contexto="teste"), [])

    @patch.object(ddg.time, "sleep")
    @patch.object(ddg, "request")
    def test_sucesso_reseta_contador_403(self, mock_request, _sleep):
        bloqueado = MagicMock()
        bloqueado.status_code = 403
        ok = MagicMock()
        ok.status_code = 200
        ok.text = ""
        mock_request.side_effect = [bloqueado, ok]
        with patch.object(ddg, "extrair_resultados", return_value=[{"titulo": "x", "url": "http://a", "snippet": ""}]):
            out = ddg.buscar("q", contexto="t")
        self.assertEqual(len(out), 1)

    def test_mensagem_circuit_breaker(self):
        ddg._circuit_breaker_ate = ddg.time.time() + 120
        self.assertTrue(ddg.circuit_breaker_ativo())
        self.assertGreater(ddg.segundos_restantes_circuit_breaker(), 0)
        msg = ddg.mensagem_circuit_breaker()
        self.assertIsNotNone(msg)
        self.assertIn("circuit breaker", msg or "")

    @patch.object(ddg.time, "sleep")
    @patch.object(ddg, "request")
    def test_buscar_loga_quando_breaker_ativo(self, mock_request, _sleep):
        ddg._circuit_breaker_ate = ddg.time.time() + 60
        with self.assertLogs("ddg_lite", level="INFO") as logs:
            self.assertEqual(ddg.buscar("q", contexto="leilao"), [])
        self.assertTrue(any("circuit breaker" in line for line in logs.output))
        mock_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
