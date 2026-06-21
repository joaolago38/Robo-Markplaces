"""
tests/test_magalu_client.py — cobertura do cliente Magalu (sem rede).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import integracoes.magalu.magalu_client as mag


def _resp(status: int, body: dict | None = None, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text or str(body or "")
    r.json.return_value = body or {}
    r.raise_for_status = MagicMock()
    return r


class TestMagaluClient(unittest.TestCase):
    @patch.object(mag, "MAGALU_MERCHANT_ID", "")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "")
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    def test_enabled_false(self):
        self.assertFalse(mag._enabled())

    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    def test_enabled_true(self):
        self.assertTrue(mag._enabled())

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    def test_listar_perguntas_403_loga_e_retorna_vazio(self, mock_request):
        mock_request.return_value = _resp(403, text="forbidden")
        with self.assertLogs("magalu_client", level="ERROR") as logs:
            out = mag.listar_perguntas_nao_respondidas()
        self.assertEqual(out, [])
        self.assertTrue(any("403" in line for line in logs.output))

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    def test_listar_perguntas_ok(self, mock_request):
        mock_request.return_value = _resp(200, {"data": [{"id": "q1"}]})
        self.assertEqual(len(mag.listar_perguntas_nao_respondidas()), 1)

    @patch.object(mag, "listar_perguntas_nao_respondidas", return_value=[{"id": 1}])
    @patch.object(mag, "registrar_acesso")
    @patch.object(mag, "dias_sem_acesso", return_value=0)
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_obter_saude_conta(self, *_):
        out = mag.obter_saude_conta()
        self.assertTrue(out["configurado"])
        self.assertEqual(out["pendencias"], 1)

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_listar_pedidos_401(self, mock_request):
        mock_request.return_value = _resp(401, text="unauthorized")
        with self.assertLogs("magalu_client", level="ERROR"):
            self.assertEqual(mag.listar_pedidos(), [])

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_atualizar_preco_ok(self, mock_request):
        mock_request.return_value = _resp(200)
        self.assertTrue(mag.atualizar_preco_item("SKU1", 19.9))

    @patch.object(mag, "request", side_effect=RuntimeError("rede"))
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_atualizar_estoque_erro_rede(self, *_):
        with self.assertLogs("magalu_client", level="ERROR"):
            self.assertFalse(mag.atualizar_estoque_item("SKU1", 5))

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_probe_conexao_ok(self, mock_request):
        mock_request.return_value = _resp(200, {"data": []})
        out = mag.probe_conexao()
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
