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
from integracoes.datadog import consulta_erros as ce
from integracoes.datadog import vigia_saude as vs


class VigiaDatadogTests(unittest.TestCase):
    def test_registrar_erro_local(self):
        with patch.object(buf, "_deve_ignorar_buffer", return_value=False):
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

    def test_registrar_erro_local_ignora_pytest(self):
        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test_x (setup)"}):
            with patch("integracoes.datadog.buffer_erros.escrever_json_atomico") as mock_write:
                buf.registrar_erro_local(nome_logger="x", mensagem="erro: boom")
                mock_write.assert_not_called()

    def test_registrar_erro_local_ignora_ruido_boom(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYTEST_CURRENT_TEST", None)
        with patch("integracoes.datadog.buffer_erros.ler_json", return_value={"erros": []}):
            with patch("integracoes.datadog.buffer_erros.escrever_json_atomico") as mock_write:
                buf.registrar_erro_local(nome_logger="agente_x", mensagem="Agente erro: boom")
                mock_write.assert_not_called()

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

    def test_verificar_inatividade_ignora_ausente(self):
        fontes = [
            {
                "id": "diario",
                "nome": "Job diario",
                "path": "logs/inexistente_diario.json",
                "campo": "timestamp",
                "max_horas": 26,
                "critico": False,
                "ignorar_ausente": True,
                "ativo": True,
            }
        ]
        with patch("integracoes.datadog.vigia_saude.ROOT", buf.ROOT):
            alertas = vs.verificar_inatividade(fontes)
        self.assertEqual(alertas, [])

    def test_verificar_erros_dedup_api_com_buffer(self):
        with patch(
            "integracoes.datadog.vigia_saude.listar_erros_recentes",
            return_value=[{"mensagem": "falha na API externa", "fingerprint": "abc"}],
        ):
            with patch(
                "integracoes.datadog.vigia_saude.buscar_erros_datadog",
                return_value={
                    "ok": True,
                    "erros": [{"mensagem": "falha na API externa"}],
                },
            ):
                alertas = vs.verificar_erros_nao_tratados(limite_horas=2, incluir_api_datadog=True)
        self.assertEqual(alertas, [])

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

    def test_filtro_ignora_outros_marketplaces_mantem_ml(self):
        antigo = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        recente = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        erros = [
            {
                "fingerprint": "mag1",
                "primeira_vez": antigo,
                "ultima_vez": recente,
                "logger": "magalu_client",
                "mensagem": "Magalu listar_pedidos HTTP 401",
                "ocorrencias": 1,
            },
            {
                "fingerprint": "ml1",
                "primeira_vez": antigo,
                "ultima_vez": recente,
                "logger": "ml_client",
                "mensagem": "ML listar_pedidos HTTP 401",
                "ocorrencias": 2,
            },
            {
                "fingerprint": "tok1",
                "primeira_vez": antigo,
                "ultima_vez": recente,
                "logger": "token_manager",
                "mensagem": "Erro ao renovar token Magazine Luiza: HTTP 400",
                "ocorrencias": 5,
            },
            {
                "fingerprint": "tok2",
                "primeira_vez": antigo,
                "ultima_vez": recente,
                "logger": "token_manager",
                "mensagem": "Erro ao renovar token ML: HTTP 400",
                "ocorrencias": 3,
            },
        ]
        filtros = vs.carregar_filtros_erro("catalogo/datadog_vigia_filtros.json")
        with patch("integracoes.datadog.vigia_saude.listar_erros_recentes", return_value=erros):
            with patch(
                "integracoes.datadog.vigia_saude.buscar_erros_datadog",
                return_value={"ok": False, "erros": []},
            ):
                alertas = vs.verificar_erros_nao_tratados(limite_horas=2, filtros=filtros)
        loggers = {a["logger"] for a in alertas}
        self.assertIn("ml_client", loggers)
        self.assertIn("token_manager", loggers)
        self.assertNotIn("magalu_client", loggers)
        self.assertEqual(len(alertas), 2)

    def test_montar_mensagem_critica(self):
        msg = vs.montar_mensagem_critica(
            [{"gravidade": "critica", "texto": "Orquestrador parado", "nome": "Orquestrador 30min", "fonte_id": "orquestrador", "horas_sem_resposta": 3}],
            [{"gravidade": "critica", "texto": "Erro ML aberto", "logger": "ml_client", "horas_aberto": 4}],
            agentes_falha_ciclo=[{"id": "monitor_concorrentes", "nome": "Monitor concorrentes", "erro": "timeout"}],
        )
        self.assertIn("GRAVE", msg.upper())
        self.assertIn("Agentes com problemas", msg)
        self.assertIn("Orquestrador 30min", msg)
        self.assertIn("ml client", msg)
        self.assertIn("Monitor concorrentes", msg)

    def test_detectar_heartbeats_congelados(self):
        iguais = [
            {"gravidade": "critica", "horas_sem_resposta": 168.43},
            {"gravidade": "critica", "horas_sem_resposta": 168.43},
            {"gravidade": "critica", "horas_sem_resposta": 168.44},
        ]
        self.assertTrue(vs._detectar_heartbeats_congelados(iguais))
        recentes = [
            {"gravidade": "critica", "horas_sem_resposta": 3.0},
            {"gravidade": "critica", "horas_sem_resposta": 3.0},
            {"gravidade": "critica", "horas_sem_resposta": 3.0},
        ]
        self.assertFalse(vs._detectar_heartbeats_congelados(recentes))
        misturados = [
            {"gravidade": "critica", "horas_sem_resposta": 100.0},
            {"gravidade": "critica", "horas_sem_resposta": 50.0},
            {"gravidade": "critica", "horas_sem_resposta": 168.0},
        ]
        self.assertFalse(vs._detectar_heartbeats_congelados(misturados))

    def test_montar_mensagem_cache_congelado(self):
        msg = vs.montar_mensagem_critica(
            [
                {"gravidade": "critica", "texto": "a", "nome": "A", "fonte_id": "a", "horas_sem_resposta": 168.4},
                {"gravidade": "critica", "texto": "b", "nome": "B", "fonte_id": "b", "horas_sem_resposta": 168.4},
                {"gravidade": "critica", "texto": "c", "nome": "C", "fonte_id": "c", "horas_sem_resposta": 168.4},
            ],
            [],
        )
        self.assertIn("cache de heartbeat congelado", msg)

    def test_listar_agentes_com_problema(self):
        lista = vs.listar_agentes_com_problema(
            [{"nome": "Operação 24h", "fonte_id": "operacao_24h", "horas_sem_resposta": 5}],
            [{"logger": "agente_ads_gatilho", "horas_aberto": 2}],
            agentes_falha_ciclo=[{"id": "vendas_whatsapp", "nome": "Vendas WhatsApp"}],
        )
        nomes = [p["nome"] for p in lista]
        self.assertIn("Operação 24h", nomes)
        self.assertIn("ads gatilho", nomes)
        self.assertIn("Vendas WhatsApp", nomes)

    def test_analisar_saude_ok(self):
        with patch.object(vs, "verificar_inatividade", return_value=[]):
            with patch.object(vs, "verificar_erros_nao_tratados", return_value=[]):
                out = vs.analisar_saude([])
        self.assertTrue(out["ok"])
        self.assertFalse(out["tem_critico"])

    def test_buscar_erros_datadog_desabilitado(self):
        with patch("core.config.DD_LOGS_ENABLED", False):
            with patch("core.config.DD_API_KEY", ""):
                out = ce.buscar_erros_datadog()
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "datadog_desabilitado")

    def test_buscar_erros_datadog_sem_application_key(self):
        with patch("core.config.DD_LOGS_ENABLED", True):
            with patch("core.config.DD_API_KEY", "key"):
                with patch("core.config.DD_APPLICATION_KEY", ""):
                    out = ce.buscar_erros_datadog()
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "dd_application_key_ausente")

    def test_buscar_erros_datadog_sucesso(self):
        class FakeResp:
            status_code = 200

            def json(self):
                return {
                    "data": [
                        {
                            "id": "1",
                            "attributes": {
                                "timestamp": "2026-07-05T10:00:00Z",
                                "message": "erro teste",
                                "status": "error",
                                "service": "robo-markplaces",
                                "tags": ["env:prod"],
                            },
                        }
                    ]
                }

        with patch("core.config.DD_LOGS_ENABLED", True):
            with patch("core.config.DD_API_KEY", "key"):
                with patch("core.config.DD_APPLICATION_KEY", "app"):
                    with patch("core.config.DD_ENV", "prod"):
                        with patch("core.config.DD_SITE", "datadoghq.com"):
                            with patch("integracoes.datadog.consulta_erros.requests.post", return_value=FakeResp()):
                                out = ce.buscar_erros_datadog()
        self.assertTrue(out["ok"])
        self.assertEqual(out["total"], 1)

    def test_verificar_inatividade_stale(self):
        antigo = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        fontes = [
            {
                "id": "hb",
                "nome": "Heartbeat",
                "path": "logs/hb_test.json",
                "campo": "timestamp",
                "max_horas": 2,
                "critico": True,
                "ativo": True,
            }
        ]
        with patch("integracoes.datadog.vigia_saude.ROOT", buf.ROOT):
            with patch("integracoes.datadog.vigia_saude.ler_json", return_value={"timestamp": antigo}):
                with patch.object(buf.ROOT.__class__, "is_file", return_value=True):
                    with patch("pathlib.Path.is_file", return_value=True):
                        alertas = vs.verificar_inatividade(fontes)
        self.assertEqual(len(alertas), 1)
        self.assertEqual(alertas[0]["motivo"], "sem_resposta")

    def test_verificar_erros_com_api_datadog(self):
        with patch("integracoes.datadog.vigia_saude.listar_erros_recentes", return_value=[]):
            with patch(
                "integracoes.datadog.vigia_saude.buscar_erros_datadog",
                return_value={
                    "ok": True,
                    "erros": [{"mensagem": "falha na API externa"}],
                },
            ):
                alertas = vs.verificar_erros_nao_tratados(limite_horas=2)
        self.assertEqual(len(alertas), 1)
        self.assertEqual(alertas[0]["tipo"], "erro_datadog_api")

    def test_parse_iso_e_fmt_horas(self):
        self.assertIsNone(vs._parse_iso(""))
        dt = vs._parse_iso("2026-07-05T10:00:00Z")
        self.assertIsNotNone(dt)
        self.assertIn("min", vs._fmt_horas(0.5))
        self.assertIn("h", vs._fmt_horas(3.0))

    def test_montar_mensagem_com_outros_alertas(self):
        msg = vs.montar_mensagem_critica(
            [{"gravidade": "alta", "texto": "Componente secundário parado"}],
            [{"gravidade": "alta", "texto": "Erro API recente"}],
        )
        self.assertIn("Componente secundário", msg)
        self.assertIn("Erro API recente", msg)

    def test_listar_erros_recentes(self):
        with patch("integracoes.datadog.buffer_erros.ler_json", return_value={"erros": [{"fingerprint": "a"}]}):
            erros = buf.listar_erros_recentes(limite=5)
        self.assertEqual(len(erros), 1)

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

    @patch("integracoes.datadog.vigia_saude.analisar_saude")
    def test_main_nao_falha_se_problemas_sem_flag(self, mock_analise):
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
        with patch("agentes.infra.agente_vigia_datadog.DATADOG_VIGIA_FALHAR_PROCESSO", False):
            with patch("agentes.infra.agente_vigia_datadog.escrever_json_atomico"):
                with patch("agentes.infra.agente_vigia_datadog.ler_json", return_value={}):
                    with patch("agentes.infra.agente_vigia_datadog.carregar_fontes", return_value=[]):
                        self.assertEqual(ag.main(["--sem-alerta"]), 0)

    @patch("integracoes.datadog.vigia_saude.analisar_saude")
    def test_main_falha_se_problemas_com_flag(self, mock_analise):
        from agentes.infra import agente_vigia_datadog as ag

        mock_analise.return_value = {
            "ok": False,
            "tem_critico": True,
            "total_inatividades": 1,
            "total_erros": 0,
            "mensagem_critica": "Problema grave",
            "inatividades": [],
            "erros": [],
        }
        with patch("agentes.infra.agente_vigia_datadog.DATADOG_VIGIA_FALHAR_PROCESSO", True):
            with patch("agentes.infra.agente_vigia_datadog.escrever_json_atomico"):
                with patch("agentes.infra.agente_vigia_datadog.ler_json", return_value={}):
                    with patch("agentes.infra.agente_vigia_datadog.carregar_fontes", return_value=[]):
                        self.assertEqual(ag.main(["--sem-alerta"]), 1)


if __name__ == "__main__":
    unittest.main()
