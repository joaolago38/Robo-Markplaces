"""
tests/test_blindspots_ml_magalu.py
Cobertura dedicada às correções dos pontos cegos de confiança de dados
real-time em ML e Magalu:
  1. registrar_acesso() só deve marcar sucesso real (não em falha).
  2. listar_pedidos_detalhado() pagina e distingue falha de "sem vendas".
  3. Magalu não assume "paid" quando o status vem ausente da API.
  4. vendas_notificador alerta quando a busca falhou de verdade.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.magalu import magalu_client as mag
from integracoes.ml import ml_client


def _resp(status: int, body: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = str(body or "")
    r.json.return_value = body or {}
    r.raise_for_status = MagicMock()
    return r


class TestMlRegistrarAcessoSoEmSucesso(unittest.TestCase):
    @patch.object(ml_client, "registrar_acesso")
    @patch.object(ml_client, "buscar_reputacao_vendedor", return_value={})
    @patch.object(ml_client, "_listar_perguntas_nao_respondidas_detalhado", return_value=([], False))
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_nao_registra_acesso_quando_busca_falha(self, *_patches):
        ml_client.obter_saude_conta()
        ml_client.registrar_acesso.assert_not_called()

    @patch.object(ml_client, "registrar_acesso")
    @patch.object(ml_client, "buscar_reputacao_vendedor", return_value={})
    @patch.object(ml_client, "_listar_perguntas_nao_respondidas_detalhado", return_value=([], True))
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_registra_acesso_quando_busca_funciona(self, *_patches):
        ml_client.obter_saude_conta()
        ml_client.registrar_acesso.assert_called_once_with("mercadolivre")


class TestMagaluRegistrarAcessoSoEmSucesso(unittest.TestCase):
    @patch.object(mag, "registrar_acesso")
    @patch.object(mag, "_listar_perguntas_nao_respondidas_detalhado", return_value=([], False))
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_nao_registra_acesso_quando_busca_falha(self, *_patches):
        mag.obter_saude_conta()
        mag.registrar_acesso.assert_not_called()

    @patch.object(mag, "registrar_acesso")
    @patch.object(mag, "_listar_perguntas_nao_respondidas_detalhado", return_value=([{"id": 1}], True))
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_registra_acesso_quando_busca_funciona(self, *_patches):
        mag.obter_saude_conta()
        mag.registrar_acesso.assert_called_once_with("magalu")


class TestMlListarPedidosDetalhado(unittest.TestCase):
    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_pagina_ate_esgotar_resultados(self, _en, mock_request):
        pagina1 = _resp(200, {
            "results": [{"id": str(i), "status": "paid", "total_amount": 10, "date_created": "x", "order_items": []} for i in range(50)],
            "paging": {"total": 70},
        })
        pagina2 = _resp(200, {
            "results": [{"id": str(i), "status": "paid", "total_amount": 10, "date_created": "x", "order_items": []} for i in range(50, 70)],
            "paging": {"total": 70},
        })
        mock_request.side_effect = [pagina1, pagina2]

        pedidos, ok = ml_client.listar_pedidos_detalhado(dias=1)
        self.assertTrue(ok)
        self.assertEqual(len(pedidos), 70)
        self.assertEqual(mock_request.call_count, 2)

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_status_diferente_de_200_retorna_ok_false(self, _en, mock_request):
        mock_request.return_value = _resp(401, {})
        pedidos, ok = ml_client.listar_pedidos_detalhado(dias=1)
        self.assertFalse(ok)
        self.assertEqual(pedidos, [])
        # compatibilidade: listar_pedidos() continua retornando lista vazia
        mock_request.return_value = _resp(401, {})
        self.assertEqual(ml_client.listar_pedidos(dias=1), [])

    @patch.object(ml_client, "_request_ml", side_effect=RuntimeError("timeout"))
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_excecao_retorna_ok_false(self, _en, _mock_request):
        pedidos, ok = ml_client.listar_pedidos_detalhado(dias=1)
        self.assertFalse(ok)
        self.assertEqual(pedidos, [])

    @patch.object(ml_client, "_enabled", return_value=False)
    def test_nao_configurado_retorna_ok_false(self, _en):
        pedidos, ok = ml_client.listar_pedidos_detalhado(dias=1)
        self.assertFalse(ok)
        self.assertEqual(pedidos, [])


class TestMagaluListarPedidosDetalhado(unittest.TestCase):
    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_status_ausente_nao_assume_pago(self, mock_request):
        from datetime import datetime, timezone

        agora = datetime.now(timezone.utc).isoformat()
        mock_request.return_value = _resp(200, {
            "data": [{"id": "1", "created_at": agora}],  # sem campo "status"
        })
        pedidos, ok = mag.listar_pedidos_detalhado(dias=7)
        self.assertTrue(ok)
        self.assertEqual(len(pedidos), 1)
        self.assertEqual(pedidos[0]["status"], "desconhecido")

    @patch.object(mag, "request")
    @patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")
    def test_status_nao_200_retorna_ok_false(self, mock_request):
        mock_request.return_value = _resp(401, {})
        pedidos, ok = mag.listar_pedidos_detalhado(dias=7)
        self.assertFalse(ok)
        self.assertEqual(pedidos, [])


class TestVendasNotificadorAlertaFalha(unittest.TestCase):
    @patch("agentes.vendas_notificador.alertar_critico")
    def test_alerta_quando_busca_falhou(self, mock_alerta):
        from agentes.vendas_notificador import _checar_busca_falhou

        _checar_busca_falhou("Mercado Livre", False)
        mock_alerta.assert_called_once()

    @patch("agentes.vendas_notificador.alertar_critico")
    def test_nao_alerta_quando_busca_funcionou(self, mock_alerta):
        from agentes.vendas_notificador import _checar_busca_falhou

        _checar_busca_falhou("Mercado Livre", True)
        mock_alerta.assert_not_called()


if __name__ == "__main__":
    unittest.main()
