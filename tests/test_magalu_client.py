"""
tests/test_magalu_client.py — cobertura do cliente Magalu (sem rede).
"""
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "yaml" not in sys.modules:
    yaml_stub = types.ModuleType("yaml")
    yaml_stub.safe_load = lambda *_args, **_kwargs: {}
    yaml_stub.YAMLError = Exception
    sys.modules["yaml"] = yaml_stub

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *_args, **_kwargs: None
    sys.modules["dotenv"] = dotenv_stub

if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")

    class _Session:
        def mount(self, *_args, **_kwargs):
            return None

        def request(self, *_args, **_kwargs):
            return None

    requests_stub.Session = _Session
    requests_stub.Response = object
    sys.modules["requests"] = requests_stub

if "requests.adapters" not in sys.modules:
    adapters_stub = types.ModuleType("requests.adapters")

    class _HTTPAdapter:
        def __init__(self, *_args, **_kwargs):
            pass

    adapters_stub.HTTPAdapter = _HTTPAdapter
    sys.modules["requests.adapters"] = adapters_stub

import integracoes.magalu.magalu_client as mag


def _resp(status: int, body: dict | None = None, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text or str(body or "")
    r.json.return_value = body or {}
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = RuntimeError(f"HTTP {status}")
    return r


def _created_recente(days: int = 2) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _created_antiga(days: int = 30) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class TestProbeConexao(unittest.TestCase):
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "")
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    def test_nao_configurado(self):
        out = mag.probe_conexao()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], 0)

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_ok_200(self, mock_request):
        mock_request.return_value = _resp(200, {"data": []})
        out = mag.probe_conexao()
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], 200)
        url = mock_request.call_args[0][1]
        self.assertIn("/v0/questions", url)

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_401(self, mock_request):
        mock_request.return_value = _resp(401, text="unauthorized")
        out = mag.probe_conexao()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], 401)
        self.assertIn("token", out["msg"].lower())

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_403(self, mock_request):
        mock_request.return_value = _resp(403, text="forbidden")
        out = mag.probe_conexao()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], 403)
        self.assertIn("permissão", out["msg"].lower())

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_outro_status(self, mock_request):
        mock_request.return_value = _resp(500, text="erro servidor")
        out = mag.probe_conexao()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], 500)

    @patch.object(mag, "request", side_effect=RuntimeError("rede"))
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_excecao_rede(self, *_):
        out = mag.probe_conexao()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], 0)


class TestListarPerguntas(unittest.TestCase):
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "")
    def test_nao_configurado(self):
        self.assertEqual(mag.listar_perguntas_nao_respondidas(), [])

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_ok_formato_data(self, mock_request):
        mock_request.return_value = _resp(200, {"data": [{"id": "q1"}]})
        self.assertEqual(mag.listar_perguntas_nao_respondidas(), [{"id": "q1"}])
        url = mock_request.call_args[0][1]
        self.assertIn("/v0/questions", url)

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_ok_formato_items(self, mock_request):
        mock_request.return_value = _resp(200, {"items": [{"id": "q2"}]})
        self.assertEqual(mag.listar_perguntas_nao_respondidas(), [{"id": "q2"}])

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_status_nao_200(self, mock_request):
        mock_request.return_value = _resp(403, text="forbidden")
        self.assertEqual(mag.listar_perguntas_nao_respondidas(), [])

    @patch.object(mag, "request", side_effect=RuntimeError("rede"))
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_excecao(self, *_):
        self.assertEqual(mag.listar_perguntas_nao_respondidas(), [])


class TestResponderPergunta(unittest.TestCase):
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "")
    def test_nao_configurado(self):
        self.assertFalse(mag.responder_pergunta("q1", "resposta"))

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_sucesso(self, mock_request):
        mock_request.return_value = _resp(200)
        self.assertTrue(mag.responder_pergunta("q1", "resposta"))
        url = mock_request.call_args[0][1]
        self.assertIn("/v0/questions/q1/answer", url)

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_excecao(self, mock_request):
        mock_request.return_value = _resp(500, text="erro")
        self.assertFalse(mag.responder_pergunta("q1", "x"))


class TestManterContaAtiva(unittest.TestCase):
    @patch.object(mag, "dias_sem_acesso", return_value=0)
    def test_ja_acessado_hoje(self, mock_dias):
        with patch.object(mag, "request") as mock_request:
            out = mag.manter_conta_ativa()
        self.assertEqual(out["acao"], "já acessado hoje")
        mock_request.assert_not_called()
        mock_dias.assert_called_with("magalu")

    @patch.object(mag, "dias_sem_acesso", return_value=5)
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "")
    def test_nao_configurado(self, *_):
        out = mag.manter_conta_ativa()
        self.assertFalse(out["ok"])
        self.assertEqual(out["acao"], "não configurado")

    @patch.object(mag, "registrar_acesso")
    @patch.object(mag, "dias_sem_acesso", side_effect=[2, 0])
    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_sucesso(self, mock_request, mock_dias, mock_registrar):
        mock_request.return_value = _resp(200, {"data": []})
        out = mag.manter_conta_ativa()
        self.assertTrue(out["ok"])
        self.assertEqual(out["acao"], "keepalive executado")
        mock_registrar.assert_called_once_with("magalu")

    @patch.object(mag, "dias_sem_acesso", side_effect=[2, 2])
    @patch.object(mag, "request", side_effect=RuntimeError("keepalive"))
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_falha_keepalive(self, *_):
        out = mag.manter_conta_ativa()
        self.assertFalse(out["ok"])
        self.assertEqual(out["acao"], "falha no keepalive")


class TestObterSaudeConta(unittest.TestCase):
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "")
    def test_nao_configurado(self):
        out = mag.obter_saude_conta()
        self.assertFalse(out["configurado"])
        self.assertEqual(out["dias_sem_acesso"], 999)

    @patch.object(mag, "dias_sem_acesso", return_value=0)
    @patch.object(mag, "registrar_acesso")
    @patch.object(
        mag,
        "_listar_perguntas_nao_respondidas_detalhado",
        return_value=([{"id": 1}, {"id": 2}], True),
    )
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_configurado(self, *_):
        out = mag.obter_saude_conta()
        self.assertTrue(out["configurado"])
        self.assertEqual(out["pendencias"], 2)


class TestAtualizarPreco(unittest.TestCase):
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "")
    def test_nao_configurado(self):
        self.assertFalse(mag.atualizar_preco_item("SKU", 10))

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_sucesso(self, mock_request):
        mock_request.return_value = _resp(200)
        self.assertTrue(mag.atualizar_preco_item("SKU1", 19.9))

    @patch.object(mag, "request", side_effect=RuntimeError("rede"))
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_excecao(self, *_):
        self.assertFalse(mag.atualizar_preco_item("SKU", 10))

    @patch("core.guardrails.bloqueio_escrita_global", return_value={"ok": False, "erro": "ROBO_PAUSAR_ESCRITA"})
    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_kill_switch_bloqueia_preco(self, mock_request, *_):
        self.assertFalse(mag.atualizar_preco_item("SKU1", 19.9))
        mock_request.assert_not_called()


class TestAtualizarEstoque(unittest.TestCase):
    @patch("core.guardrails.bloqueio_escrita_global", return_value={"ok": False, "erro": "bloqueado"})
    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_kill_switch_bloqueia_sem_http(self, mock_request, *_):
        self.assertFalse(mag.atualizar_estoque_item("SKU1", 5))
        mock_request.assert_not_called()

    @patch("core.guardrails.bloqueio_escrita_global", return_value=None)
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "")
    def test_nao_configurado(self, *_):
        self.assertFalse(mag.atualizar_estoque_item("SKU1", 5))

    @patch("core.guardrails.bloqueio_escrita_global", return_value=None)
    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_sucesso(self, mock_request, *_):
        mock_request.return_value = _resp(200)
        self.assertTrue(mag.atualizar_estoque_item("SKU1", 5))

    @patch("core.guardrails.bloqueio_escrita_global", return_value=None)
    @patch.object(mag, "request", side_effect=RuntimeError("rede"))
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_excecao(self, *_):
        self.assertFalse(mag.atualizar_estoque_item("SKU1", 5))


class TestListarPedidos(unittest.TestCase):
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "")
    def test_nao_configurado(self):
        self.assertEqual(mag.listar_pedidos(), [])

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_pedido_recente_dentro_janela(self, mock_request):
        mock_request.return_value = _resp(
            200,
            {
                "data": [
                    {
                        "code": "ORD1",
                        "status": "paid",
                        "total": 99.9,
                        "created_at": _created_recente(2),
                        "items": [{"sku": "SKU1", "quantity": 1, "price": 99.9}],
                    }
                ]
            },
        )
        pedidos = mag.listar_pedidos(dias=7)
        self.assertEqual(len(pedidos), 1)
        self.assertEqual(pedidos[0]["order_id"], "ORD1")
        self.assertEqual(pedidos[0]["itens"][0]["sku"], "SKU1")

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_pedido_antigo_filtrado(self, mock_request):
        mock_request.return_value = _resp(
            200,
            {
                "data": [
                    {
                        "code": "ORD-VELHO",
                        "status": "paid",
                        "total": 10,
                        "created_at": _created_antiga(30),
                        "items": [],
                    }
                ]
            },
        )
        self.assertEqual(mag.listar_pedidos(dias=7), [])

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_pedido_sem_id_ignorado(self, mock_request):
        mock_request.return_value = _resp(
            200,
            {
                "data": [
                    {
                        "status": "paid",
                        "total": 10,
                        "created_at": _created_recente(1),
                        "items": [],
                    }
                ]
            },
        )
        self.assertEqual(mag.listar_pedidos(dias=7), [])

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_status_nao_200(self, mock_request):
        mock_request.return_value = _resp(401, text="unauthorized")
        self.assertEqual(mag.listar_pedidos(), [])

    @patch.object(mag, "request", side_effect=RuntimeError("rede"))
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_excecao(self, *_):
        self.assertEqual(mag.listar_pedidos(), [])

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_body_nao_lista(self, mock_request):
        mock_request.return_value = _resp(200, {"data": "invalido"})
        self.assertEqual(mag.listar_pedidos(), [])


class TestHelpers(unittest.TestCase):
    @patch.object(mag, "MAGALU_REFRESH_TOKEN", "rt")
    @patch.object(mag, "get_token_magalu", return_value="refreshed")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_headers_usa_token_renovado(self, *_):
        headers = mag._h()
        self.assertEqual(headers["Authorization"], "Bearer refreshed")
        self.assertNotIn("X-Seller-Id", headers)


if __name__ == "__main__":
    unittest.main()
