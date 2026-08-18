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
    @patch.object(ddg, "_ddg_request")
    def test_circuit_breaker_apos_varias_403(self, mock_request, _sleep):
        from core.config import DDG_FALHAS_403_PARA_BREAKER

        bloqueado = MagicMock()
        bloqueado.status_code = 403
        mock_request.return_value = bloqueado
        for _ in range(DDG_FALHAS_403_PARA_BREAKER):
            ddg.buscar("teste", contexto="teste")
        self.assertEqual(ddg.buscar("outra", contexto="teste"), [])

    @patch.object(ddg.time, "sleep")
    @patch.object(ddg, "_ddg_request")
    def test_sucesso_reseta_contador_403(self, mock_request, _sleep):
        bloqueado = MagicMock()
        bloqueado.status_code = 403
        bloqueado.text = ""
        ok = MagicMock()
        ok.status_code = 200
        ok.text = ""
        mock_request.side_effect = [bloqueado, ok]
        with patch.object(ddg, "extrair_resultados_lite", return_value=[{"titulo": "x", "url": "http://a", "snippet": ""}]):
            out = ddg.buscar("q", contexto="t")
        self.assertEqual(len(out), 1)

    def test_mensagem_circuit_breaker(self):
        ddg._breaker_ate_por_contexto["geral"] = ddg.time.time() + 120
        self.assertTrue(ddg.circuit_breaker_ativo("geral"))
        self.assertGreater(ddg.segundos_restantes_circuit_breaker("geral"), 0)
        msg = ddg.mensagem_circuit_breaker("geral")
        self.assertIsNotNone(msg)
        self.assertIn("circuit breaker", msg or "")

    @patch.object(ddg.time, "sleep")
    @patch.object(ddg, "_ddg_request")
    def test_buscar_loga_quando_breaker_ativo(self, mock_request, _sleep):
        ddg._breaker_ate_por_contexto["leilao"] = ddg.time.time() + 60
        with self.assertLogs("ddg_lite", level="INFO") as logs:
            self.assertEqual(ddg.buscar("q", contexto="leilao"), [])
        self.assertTrue(any("circuit breaker" in line for line in logs.output))
        mock_request.assert_not_called()

    @patch.object(ddg.time, "sleep")
    @patch.object(ddg, "_ddg_request")
    def test_breaker_isolado_por_contexto(self, mock_request, _sleep):
        from core.config import DDG_FALHAS_403_PARA_BREAKER

        bloqueado = MagicMock()
        bloqueado.status_code = 403
        bloqueado.text = ""
        mock_request.return_value = bloqueado
        for _ in range(DDG_FALHAS_403_PARA_BREAKER):
            ddg.buscar("leilao", contexto="leilao")
        self.assertTrue(ddg.circuit_breaker_ativo("leilao"))
        self.assertFalse(ddg.circuit_breaker_ativo("ml_busca_termo"))

    def test_extrair_resultados_lite(self):
        html = """
        <a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fcopart.com.br%2Flote" class='result-link'>Fiat Uno leilão</a>
        <td class='result-snippet'>Veículo em leilão Copart</td>
        <span class='link-text'>www.copart.com.br/lote</span>
        """
        itens = ddg.extrair_resultados_lite(html)
        self.assertEqual(len(itens), 1)
        self.assertIn("copart.com.br", itens[0]["url"])

    @patch.object(ddg.time, "sleep")
    @patch.object(ddg, "_buscar_html")
    @patch.object(ddg, "_buscar_lite")
    def test_auto_fallback_para_html(self, mock_lite, mock_html, _sleep):
        mock_lite.return_value = (200, [])
        mock_html.return_value = (
            200,
            [{"titulo": "x", "url": "https://example.com", "snippet": ""}],
        )
        with patch("core.config.DDG_BACKEND", "auto"):
            out = ddg.buscar("q", contexto="t")
        self.assertEqual(len(out), 1)
        mock_html.assert_called_once()

    @patch.object(ddg.time, "sleep")
    @patch.object(ddg, "_buscar_lite", return_value=(200, []))
    def test_vazio_nao_sobe_info(self, _lite, _sleep):
        with self.assertLogs("ddg_lite", level="DEBUG") as logs:
            self.assertEqual(ddg.buscar("q", contexto="mp_shopee.com.br"), [])
        self.assertFalse(any("INFO" in line for line in logs.output))
        self.assertTrue(any("DDG lite vazio" in line for line in logs.output))

    @patch.object(ddg.time, "sleep")
    @patch.object(ddg, "_buscar_lite", return_value=(200, []))
    def test_vazio_nao_sobe_info(self, _lite, _sleep):
        with self.assertLogs("ddg_lite", level="DEBUG") as logs:
            self.assertEqual(ddg.buscar("q", contexto="mp_shopee.com.br"), [])
        self.assertFalse(any("INFO" in line for line in logs.output))
        self.assertTrue(any("DDG lite vazio" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
