"""
tests/test_magalu_client.py — cobertura do cliente Magalu (sem rede).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import integracoes.magalu.magalu_client as mag


def _iso_utc_days_ago(days: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


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

    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    def test_desligado_listar_pedidos(self):
        self.assertEqual(mag.listar_pedidos(), [])

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_responder_pergunta_ok(self, mock_request):
        mock_request.return_value = _resp(200)
        self.assertTrue(mag.responder_pergunta("q1", "resposta"))

    @patch.object(mag, "request", side_effect=RuntimeError("rede"))
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_atualizar_preco_erro(self, *_):
        with self.assertLogs("magalu_client", level="ERROR"):
            self.assertFalse(mag.atualizar_preco_item("SKU", 10))

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
    def test_listar_pedidos_ok(self, mock_request):
        mock_request.return_value = _resp(
            200,
            {
                "data": [
                    {
                        "code": "ORD1",
                        "status": "paid",
                        "total": 99.9,
                        "created_at": _iso_utc_days_ago(2),
                        "items": [{"sku": "SKU1", "quantity": 1, "price": 99.9}],
                    }
                ]
            },
        )
        pedidos = mag.listar_pedidos(dias=7)
        self.assertEqual(len(pedidos), 1)
        self.assertEqual(pedidos[0]["order_id"], "ORD1")

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_atualizar_estoque_ok(self, mock_request):
        mock_request.return_value = _resp(200)
        self.assertTrue(mag.atualizar_estoque_item("SKU1", 5))

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_probe_conexao_403(self, mock_request):
        mock_request.return_value = _resp(403, text="forbidden")
        out = mag.probe_conexao()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], 403)

    @patch.object(mag, "registrar_acesso")
    @patch.object(mag, "dias_sem_acesso", return_value=0)
    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_manter_conta_ativa_ok(self, mock_request, *_):
        mock_request.return_value = _resp(200, {"data": []})
        out = mag.manter_conta_ativa()
        self.assertTrue(out["ok"])

    @patch.object(mag, "dias_sem_acesso", return_value=5)
    @patch.object(mag, "MAGALU_MERCHANT_ID", "")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "")
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    def test_manter_conta_nao_configurado(self, *_):
        out = mag.manter_conta_ativa()
        self.assertFalse(out["ok"])

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_probe_conexao_401(self, mock_request):
        mock_request.return_value = _resp(401, text="unauthorized")
        out = mag.probe_conexao()
        self.assertEqual(out["status"], 401)

    @patch.object(mag, "request", side_effect=RuntimeError("rede"))
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_listar_pedidos_excecao(self, *_):
        with self.assertLogs("magalu_client", level="ERROR"):
            self.assertEqual(mag.listar_pedidos(), [])

    @patch.object(mag, "get_token_magalu", return_value="refreshed")
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "rt")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_headers_usa_token_renovado(self, *_):
        headers = mag._h()
        self.assertEqual(headers["Authorization"], "Bearer refreshed")

    def test_probe_desligado(self):
        with patch.object(mag, "MAGALU_MERCHANT_ID", ""):
            out = mag.probe_conexao()
            self.assertFalse(out["ok"])

    @patch.object(mag, "MAGALU_MERCHANT_ID", "")
    def test_listar_perguntas_desligado(self, *_):
        self.assertEqual(mag.listar_perguntas_nao_respondidas(), [])

    @patch.object(mag, "MAGALU_MERCHANT_ID", "")
    def test_atualizar_preco_desligado(self, *_):
        with self.assertLogs("magalu_client", level="WARNING"):
            self.assertFalse(mag.atualizar_preco_item("SKU", 1))

    @patch.object(mag, "request", side_effect=RuntimeError("keepalive"))
    @patch.object(mag, "dias_sem_acesso", return_value=5)
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_manter_conta_ativa_falha(self, *_):
        with self.assertLogs("magalu_client", level="ERROR"):
            out = mag.manter_conta_ativa()
        self.assertFalse(out["ok"])

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_responder_pergunta_falha_http(self, mock_request):
        resp = _resp(500, text="erro")
        resp.raise_for_status.side_effect = RuntimeError("500")
        mock_request.return_value = resp
        with self.assertLogs("magalu_client", level="ERROR"):
            self.assertFalse(mag.responder_pergunta("q1", "x"))

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_MERCHANT_ID", "m1")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_probe_conexao_ok(self, mock_request):
        mock_request.return_value = _resp(200, {"data": []})
        out = mag.probe_conexao()
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
