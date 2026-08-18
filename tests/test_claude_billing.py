"""tests/test_claude_billing.py"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from core import claude_billing as b


class TestClaudeBilling(unittest.TestCase):
    def test_centavos_para_usd(self):
        self.assertAlmostEqual(b.centavos_para_usd("123.45"), 1.2345, places=4)
        self.assertEqual(b.centavos_para_usd(None), 0.0)
        self.assertEqual(b.centavos_para_usd("x"), 0.0)

    def test_somar_custo_relatorio(self):
        payload = {
            "data": [
                {
                    "results": [
                        {"amount": "344.00"},
                        {"amount": "100.00"},
                    ]
                }
            ]
        }
        self.assertAlmostEqual(b.somar_custo_relatorio(payload), 4.44, places=2)

    def test_consulta_sem_admin_key(self):
        with patch.object(b, "chave_admin", return_value=""):
            out = b.consultar_custo_mes_console()
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "sem_admin_api_key")

    def test_consulta_ok_paginada(self):
        r1 = MagicMock()
        r1.status_code = 200
        r1.content = b"1"
        r1.json.return_value = {
            "data": [{"results": [{"amount": "241.00"}]}],
            "has_more": True,
            "next_page": "page2",
        }
        r2 = MagicMock()
        r2.status_code = 200
        r2.content = b"1"
        r2.json.return_value = {
            "data": [{"results": [{"amount": "103.00"}]}],
            "has_more": False,
            "next_page": None,
        }
        with (
            patch.object(b, "chave_admin", return_value="sk-ant-admin-test"),
            patch.object(b, "request", side_effect=[r1, r2]) as mock_req,
        ):
            out = b.consultar_custo_mes_console(
                agora=datetime(2026, 8, 17, tzinfo=timezone.utc)
            )
        self.assertTrue(out["ok"])
        self.assertAlmostEqual(out["gasto_mes_usd"], 3.44, places=2)
        self.assertEqual(mock_req.call_count, 2)

    def test_consulta_http_erro(self):
        resp = MagicMock()
        resp.status_code = 403
        with (
            patch.object(b, "chave_admin", return_value="sk-ant-admin-test"),
            patch.object(b, "request", return_value=resp),
        ):
            out = b.consultar_custo_mes_console()
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "http_403")

    def test_sonda_sem_api_key(self):
        with patch("core.config.ANTHROPIC_API_KEY", ""):
            out = b.sondar_credito_disponivel()
        self.assertFalse(out["ok"])
        self.assertIsNone(out["com_credito"])

    def test_sonda_api_ok_tem_credito(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "{}"
        with (
            patch("core.config.ANTHROPIC_API_KEY", "sk-test"),
            patch.object(b, "request", return_value=resp),
        ):
            out = b.sondar_credito_disponivel()
        self.assertTrue(out["ok"])
        self.assertTrue(out["com_credito"])

    def test_sonda_api_sem_credito(self):
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Your credit balance is too low to access this model"
        with (
            patch("core.config.ANTHROPIC_API_KEY", "sk-test"),
            patch.object(b, "request", return_value=resp),
        ):
            out = b.sondar_credito_disponivel()
        self.assertTrue(out["ok"])
        self.assertFalse(out["com_credito"])
        self.assertEqual(out["motivo"], "credit_too_low")


if __name__ == "__main__":
    unittest.main()
