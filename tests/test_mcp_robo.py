"""
tests/test_mcp_robo.py — MCP local do robô (ferramentas + JSON-RPC).
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.mcp import ferramentas, servidor


class TestFerramentasMcp(unittest.TestCase):
    def test_ultimo_ciclo_ausente(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ferramentas, "CICLO_PATH", Path(tmp) / "ciclo.json"):
                out = ferramentas.ultimo_ciclo()
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "ciclo_ausente")

    def test_ultimo_ciclo_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ciclo.json"
            path.write_text('{"timestamp": "2026-08-18T12:00:00+00:00", "ok": true, "falhas": 0}', encoding="utf-8")
            with patch.object(ferramentas, "CICLO_PATH", path):
                out = ferramentas.ultimo_ciclo()
        self.assertTrue(out["ok"])
        self.assertEqual(out["falhas"], 0)

    def test_datadog_erros_delega(self):
        fake = {"ok": True, "erros": [], "total": 0}
        with patch.object(ferramentas, "buscar_erros_datadog", return_value=fake) as mock_b:
            out = ferramentas.datadog_erros(horas=1, limite=10)
        self.assertEqual(out, fake)
        mock_b.assert_called_once_with(horas=1.0, limite=10)

    def test_vigia_saude_formata(self):
        with patch.object(ferramentas, "carregar_fontes", return_value=[]):
            with patch.object(
                ferramentas,
                "analisar_saude",
                return_value={
                    "ok": False,
                    "tem_critico": True,
                    "total_inatividades": 2,
                    "total_erros": 0,
                    "agentes_com_problema": [{"id": "chat", "nome": "Chat"}],
                    "inatividades": [{"fonte_id": "chat"}],
                    "erros": [],
                },
            ):
                out = ferramentas.vigia_saude()
        self.assertFalse(out["ok"])
        self.assertEqual(out["total_inatividades"], 2)
        self.assertEqual(out["agentes_com_problema"][0]["id"], "chat")


class TestServidorMcp(unittest.TestCase):
    def test_initialize_e_tools_list(self):
        init = servidor.tratar_requisicao(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            }
        )
        self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(init["result"]["serverInfo"]["name"], "robo-markplaces")

        listed = servidor.tratar_requisicao({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        nomes = {t["name"] for t in listed["result"]["tools"]}
        self.assertEqual(nomes, {"vigia_saude", "ultimo_ciclo", "datadog_erros"})

    def test_notificacao_nao_responde(self):
        self.assertIsNone(
            servidor.tratar_requisicao({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )

    def test_tool_desconhecida(self):
        resp = servidor.tratar_requisicao(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "nao_existe", "arguments": {}},
            }
        )
        self.assertEqual(resp["error"]["code"], -32601)

    def test_tools_call_ultimo_ciclo(self):
        with patch.object(ferramentas, "ultimo_ciclo", return_value={"ok": True, "falhas": 0}):
            resp = servidor.tratar_requisicao(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "ultimo_ciclo", "arguments": {}},
                }
            )
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(payload["ok"])
        self.assertFalse(resp["result"]["isError"])

    def test_tools_call_datadog_erros_args(self):
        with patch.object(ferramentas, "datadog_erros", return_value={"ok": False, "motivo": "x"}) as mock_d:
            servidor.tratar_requisicao(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "datadog_erros", "arguments": {"horas": 6, "limite": 5}},
                }
            )
        mock_d.assert_called_once_with(horas=6.0, limite=5)

    def test_framing_content_length(self):
        msg = {"jsonrpc": "2.0", "id": 1, "result": {"pong": True}}
        buf = io.BytesIO()
        servidor._escrever(msg, buf)
        raw = buf.getvalue()
        self.assertTrue(raw.startswith(b"Content-Length:"))
        inp = io.BytesIO(raw)
        lido = servidor._ler(inp)
        self.assertEqual(lido, msg)

    def test_ler_ndjson(self):
        linha = json.dumps({"jsonrpc": "2.0", "method": "ping", "id": 9}) + "\n"
        lido = servidor._ler(io.BytesIO(linha.encode("utf-8")))
        self.assertEqual(lido["method"], "ping")
