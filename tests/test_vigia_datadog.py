"""
tests/test_vigia_datadog.py
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.datadog import buffer_erros as buf
from integracoes.datadog import vigia_saude as vs


class VigiaDatadogTests(unittest.TestCase):
    def test_registrar_erro_local(self):
        with patch.object(buf, "BUFFER_PATH") as mock_path:
            mock_path.exists.return_value = False
            with patch("integracoes.datadog.buffer_erros.ler_json", return_value={"erros": []}):
                with patch("integracoes.datadog.buffer_erros.escrever_json_atomico") as mock_write:
                    buf.registrar_erro_local(
                        nome_logger="ml_client",
                        mensagem="token expirado",
                        error_kind="http_401",
                    )
                    mock_write.assert_called_once()
                    payload = mock_write.call_args[0][1]
                    self.assertEqual(len(payload["erros"]), 1)

    def test_verificar_inatividade_sem_arquivo(self):
        fontes = [
            {
                "id": "teste",
                "nome": "Teste",
                "path": "logs/inexistente_xyz.json",
                "campo": "timestamp",
                "max_horas": 2,
                "critico": True,
                "ativo": True,
            }
        ]
        with patch("integracoes.datadog.vigia_saude.ROOT", buf.ROOT):
            alertas = vs.verificar_inatividade(fontes)
        self.assertEqual(len(alertas), 1)
        self.assertEqual(alertas[0]["motivo"], "arquivo_ausente")

    def test_verificar_erros_nao_tratados(self):
        antigo = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        recente = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        erros = [
            {
                "fingerprint": "abc123",
                "primeira_vez": antigo,
                "ultima_vez": recente,
                "logger": "ml_client",
                "mensagem": "401 unauthorized",
                "ocorrencias": 5,
            }
        ]
        with patch("integracoes.datadog.vigia_saude.listar_erros_recentes", return_value=erros):
            with patch(
                "integracoes.datadog.vigia_saude.buscar_erros_datadog",
                return_value={"ok": False, "erros": []},
            ):
                alertas = vs.verificar_erros_nao_tratados(limite_horas=2)
        self.assertEqual(len(alertas), 1)
        self.assertEqual(alertas[0]["gravidade"], "critica")

    def test_montar_mensagem_critica(self):
        msg = vs.montar_mensagem_critica(
            [{"gravidade": "critica", "texto": "Orquestrador parado"}],
            [{"gravidade": "critica", "texto": "Erro ML aberto"}],
        )
        self.assertIn("GRAVE", msg.upper())
        self.assertIn("Orquestrador", msg)

    @patch("agentes.infra.agente_vigia_datadog.alertar_critico", return_value=True)
    @patch("integracoes.datadog.vigia_saude.analisar_saude")
    def test_agente_executar_critico(self, mock_analise, _mock_critico):
        from agentes.infra import agente_vigia_datadog as ag

        mock_analise.return_value = {
            "ok": False,
            "tem_critico": True,
            "total_inatividades": 1,
            "total_erros": 1,
            "mensagem_critica": "Problema grave",
            "inatividades": [],
            "erros": [],
        }
        with patch("agentes.infra.agente_vigia_datadog.escrever_json_atomico"):
            with patch("agentes.infra.agente_vigia_datadog.ler_json", return_value={}):
                out = ag.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["tem_critico"])


if __name__ == "__main__":
    unittest.main()
