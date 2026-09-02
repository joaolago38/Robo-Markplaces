"""tests/test_claude_orcamento.py"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import claude_orcamento as o


class TestClaudeOrcamento(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "uso.json"
        self.painel = Path(self.tmp.name) / "painel.json"
        self.hist = Path(self.tmp.name) / "hist.json"
        self.patcher = patch.object(o, "USO_PATH", self.path)
        self.patcher.start()
        self._p_painel = patch.object(o, "PAINEL_PATH", self.painel)
        self._p_painel.start()
        self._p_hist = patch.object(o, "HIST_PATH", self.hist)
        self._p_hist.start()

    def tearDown(self):
        self._p_hist.stop()
        self._p_painel.stop()
        self.patcher.stop()
        self.tmp.cleanup()

    @patch.object(o, "_talvez_alertar")
    def test_registrar_e_restante(self, _alerta):
        teto = 22.0
        with patch.object(o, "_cfg") as cfg:
            cfg.return_value.CLAUDE_ORCAMENTO_USD = teto
            cfg.return_value.CLAUDE_ORCAMENTO_ATIVO = True
            cfg.return_value.CLAUDE_PRECO_HAIKU_IN = 1.0
            cfg.return_value.CLAUDE_PRECO_HAIKU_OUT = 5.0
            out = o.registrar_uso(
                modelo="claude-haiku-4-5",
                input_tokens=1_000_000,
                output_tokens=0,
                origem="agentes.teste",
            )
            self.assertTrue(out["ok"])
            self.assertAlmostEqual(out["custo_usd"], 1.0, places=4)
            r = out["resumo"]
            self.assertAlmostEqual(r["consumido_usd"], 1.0, places=4)
            self.assertAlmostEqual(r["orcamento_usd"], teto, places=4)
            self.assertAlmostEqual(r["restante_usd"], teto - 1.0, places=4)
            self.assertIn("agentes.teste", r["por_origem"])
            r2 = o.resumo()
            self.assertAlmostEqual(r2["restante_usd"], teto - 1.0, places=4)

    @patch.object(o, "_talvez_alertar")
    def test_hard_stop(self, _alerta):
        with patch.object(o, "_cfg") as cfg:
            cfg.return_value.CLAUDE_ORCAMENTO_USD = 0.5
            cfg.return_value.CLAUDE_ORCAMENTO_ATIVO = True
            cfg.return_value.CLAUDE_PRECO_HAIKU_IN = 1.0
            cfg.return_value.CLAUDE_PRECO_HAIKU_OUT = 5.0
            o.registrar_uso(
                modelo="claude-haiku-4-5",
                input_tokens=1_000_000,
                output_tokens=0,
                origem="x",
            )
            with patch(
                "core.claude_toggle.claude_esta_ativo",
                return_value=(True, ""),
            ):
                ok, motivo = o.pode_chamar()
        self.assertFalse(ok)
        self.assertIn("esgotado", motivo)

    def test_pode_chamar_fail_closed_toggle_quebra(self):
        with patch(
            "core.claude_toggle.claude_esta_ativo",
            side_effect=RuntimeError("boom"),
        ):
            ok, motivo = o.pode_chamar()
        self.assertFalse(ok)
        self.assertIn("toggle_indisponivel", motivo)

    @patch.object(o, "_talvez_alertar")
    def test_assertividade_por_origem(self, _alerta):
        with patch.object(o, "_cfg") as cfg:
            cfg.return_value.CLAUDE_ORCAMENTO_USD = 8.99
            cfg.return_value.CLAUDE_ORCAMENTO_ATIVO = True
            cfg.return_value.CLAUDE_PRECO_HAIKU_IN = 1.0
            cfg.return_value.CLAUDE_PRECO_HAIKU_OUT = 5.0
            o.registrar_uso(
                modelo="claude-haiku-4-5",
                input_tokens=1000,
                output_tokens=100,
                origem="agentes.panorama",
                resultado="ok",
            )
            o.registrar_uso(
                modelo="claude-haiku-4-5",
                input_tokens=1000,
                output_tokens=100,
                origem="agentes.panorama",
                resultado="falha",
            )
            r = o.resumo()
        self.assertEqual(r["assertividade_pct"], 50.0)
        self.assertEqual(r["por_origem"]["agentes.panorama"]["assertividade_pct"], 50.0)

    def test_classificar_resultado(self):
        self.assertEqual(o.classificar_resultado_texto("Resposta útil"), "ok")
        self.assertEqual(o.classificar_resultado_texto("⚠️ Erro na IA: falha"), "falha")
        self.assertEqual(o.classificar_resultado_texto("⚠️ Claude pausado: orçamento"), "bloqueado")
        self.assertEqual(o.classificar_resultado_texto(""), "vazio")

    def test_mensagem_tem_assertividade(self):
        msg = o.montar_mensagem_telegram(
            {
                "orcamento_usd": 8.99,
                "consumido_usd": 1.2,
                "restante_usd": 7.79,
                "percentual_usado": 13.3,
                "chamadas": 3,
                "tokens_in": 100,
                "tokens_out": 50,
                "bloqueado": False,
                "assertividade_pct": 66.7,
                "resultados": {"ok": 2, "falha": 1, "fallback": 0, "vazio": 0, "bloqueado": 0},
                "por_origem": {
                    "agentes.panorama": {
                        "usd": 1.0,
                        "chamadas": 3,
                        "ok": 2,
                        "falha": 1,
                        "assertividade_pct": 66.7,
                    }
                },
                "por_modelo": {"claude-haiku-4-5": {"usd": 1.2, "chamadas": 3, "assertividade_pct": 66.7}},
            }
        )
        self.assertIn("Assertividade", msg)
        self.assertIn("66.7", msg)

    def test_estimar_haiku(self):
        with patch.object(o, "_cfg") as cfg:
            cfg.return_value.CLAUDE_PRECO_HAIKU_IN = 1.0
            cfg.return_value.CLAUDE_PRECO_HAIKU_OUT = 5.0
            c = o.estimar_custo_usd("claude-haiku-4-5", 500_000, 100_000)
        self.assertAlmostEqual(c, 0.5 + 0.5, places=4)

    @patch.object(o, "_talvez_alertar")
    def test_ranking_e_historico(self, _alerta):
        hist = Path(self.tmp.name) / "hist.json"
        with patch.object(o, "HIST_PATH", hist), patch.object(o, "_cfg") as cfg:
            cfg.return_value.CLAUDE_ORCAMENTO_USD = 8.99
            cfg.return_value.CLAUDE_ORCAMENTO_ATIVO = True
            cfg.return_value.CLAUDE_PRECO_HAIKU_IN = 1.0
            cfg.return_value.CLAUDE_PRECO_HAIKU_OUT = 5.0
            o.registrar_uso(
                modelo="claude-haiku-4-5",
                input_tokens=100_000,
                output_tokens=0,
                origem="agentes.alfa",
            )
            o.registrar_uso(
                modelo="claude-haiku-4-5",
                input_tokens=50_000,
                output_tokens=0,
                origem="agentes.beta",
            )
            rank = o.ranking_consumo_por_agente()
        self.assertEqual(rank[0]["agente"], "agentes.alfa")
        self.assertAlmostEqual(rank[0]["usd"], 0.1, places=4)
        self.assertAlmostEqual(rank[1]["usd"], 0.05, places=4)
        with patch.object(o, "HIST_PATH", hist):
            p1 = o.registrar_ponto_historico()
            p2 = o.registrar_ponto_historico()
        self.assertGreaterEqual(len(p1), 1)
        self.assertGreaterEqual(len(p2), 1)

    def test_mensagem_consumo_por_agente(self):
        msg = o.montar_mensagem_telegram(
            {
                "orcamento_usd": 8.99,
                "consumido_usd": 1.5,
                "restante_usd": 7.49,
                "percentual_usado": 16.7,
                "chamadas": 2,
                "tokens_in": 0,
                "tokens_out": 0,
                "bloqueado": False,
                "assertividade_pct": 100.0,
                "resultados": {"ok": 2, "falha": 0, "fallback": 0, "vazio": 0, "bloqueado": 0},
                "por_origem": {
                    "agentes.a": {"usd": 1.0, "chamadas": 1, "ok": 1, "assertividade_pct": 100},
                    "agentes.b": {"usd": 0.5, "chamadas": 1, "ok": 1, "assertividade_pct": 100},
                },
                "por_modelo": {},
            }
        )
        self.assertIn("Consumo por agente (US$)", msg)
        self.assertIn("US$ 1.0000", msg)
        self.assertIn("US$ 0.5000", msg)

    @patch.object(o, "_talvez_alertar")
    def test_gerar_graficos_consumo_sem_matplotlib(self, _alerta):
        hist = Path(self.tmp.name) / "hist.json"
        png_a = Path(self.tmp.name) / "a.png"
        png_e = Path(self.tmp.name) / "e.png"
        with (
            patch.object(o, "HIST_PATH", hist),
            patch.object(o, "GRAFICO_AGENTES_PATH", png_a),
            patch.object(o, "GRAFICO_EVOLUCAO_PATH", png_e),
            patch.object(o, "_cfg") as cfg,
        ):
            cfg.return_value.CLAUDE_ORCAMENTO_USD = 8.99
            cfg.return_value.CLAUDE_ORCAMENTO_ATIVO = True
            cfg.return_value.CLAUDE_PRECO_HAIKU_IN = 1.0
            cfg.return_value.CLAUDE_PRECO_HAIKU_OUT = 5.0
            o.registrar_uso(
                modelo="claude-haiku-4-5",
                input_tokens=100_000,
                output_tokens=0,
                origem="agentes.alfa",
            )
            with patch("core.graficos.disponivel", return_value=False):
                out = o.gerar_graficos_consumo()
        self.assertEqual(out["metrica_barras"], "usd")
        self.assertIsNone(out["por_agente"])
        self.assertGreaterEqual(out["historico_pontos"], 1)
        self.assertEqual(out["ranking"][0]["agente"], "agentes.alfa")

    def test_nome_agente_curto(self):
        curto = o._nome_agente_curto("a" * 50, max_len=10)
        self.assertEqual(len(curto), 10)
        self.assertTrue(curto.startswith("…"))

    def test_detectar_origem_path_windows(self):
        class _Fr:
            def __init__(self, filename):
                self.filename = filename

        with patch(
            "core.claude_orcamento.traceback.extract_stack",
            return_value=[
                _Fr(r"C:\proj\Robo-Markplaces\agentes\panorama\agente_panorama.py"),
                _Fr(r"C:\proj\Robo-Markplaces\core\claude_client.py"),
            ],
        ):
            self.assertEqual(o.detectar_origem(), "panorama.agente_panorama")

    def test_detectar_origem_path_linux_actions(self):
        class _Fr:
            def __init__(self, filename):
                self.filename = filename

        with patch(
            "core.claude_orcamento.traceback.extract_stack",
            return_value=[
                _Fr("/home/runner/work/repo/agentes/ml/agente_monitor_ml.py"),
                _Fr("/home/runner/work/repo/core/claude_client.py"),
            ],
        ):
            self.assertEqual(o.detectar_origem(), "ml.agente_monitor_ml")

    def test_resumo_usa_snapshot_console_quando_cache_zerou(self):
        self.path.write_text(
            '{"orcamento_usd": 8.99, "consumido_usd": 0, "fonte_saldo": "console_painel",'
            ' "saldo_console_usd": 2.41, "gasto_mes_console_usd": 3.44,'
            ' "resultados": {"ok": 0, "falha": 0, "fallback": 0, "vazio": 0, "bloqueado": 0},'
            ' "por_origem": {}, "por_modelo": {}}',
            encoding="utf-8",
        )
        r = o.resumo()
        self.assertAlmostEqual(r["restante_usd"], 2.41, places=2)
        self.assertAlmostEqual(r["consumido_usd"], 3.44, places=2)
        self.assertEqual(r["fonte_saldo"], "console_painel")
        self.assertFalse(r["bloqueado"])

    @patch.object(o, "_talvez_alertar")
    def test_registrar_uso_nao_reseta_orcamento_console(self, _alerta):
        o.aplicar_saldo_console(2.41, gasto_mes_usd=3.44, emitir_datadog=False)
        with patch.object(o, "_cfg") as cfg:
            cfg.return_value.CLAUDE_ORCAMENTO_USD = 8.99
            cfg.return_value.CLAUDE_ORCAMENTO_ATIVO = True
            cfg.return_value.CLAUDE_PRECO_HAIKU_IN = 1.0
            cfg.return_value.CLAUDE_PRECO_HAIKU_OUT = 5.0
            o.registrar_uso(
                modelo="claude-haiku-4-5",
                input_tokens=0,
                output_tokens=0,
                origem="teste",
                resultado="bloqueado",
            )
        r = o.resumo()
        self.assertAlmostEqual(r["restante_usd"], 2.41, places=2)
        self.assertLess(r["orcamento_usd"], 8.0)

    @patch("core.datadog_metrics.gauge")
    def test_emitir_metricas_billing_datadog(self, mock_gauge):
        r = {
            "consumido_usd": 3.44,
            "restante_usd": 0.0,
            "orcamento_usd": 3.44,
            "assertividade_pct": 40.0,
            "fonte_saldo": "console_api",
        }
        o.emitir_metricas_claude_datadog(r)
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("ia.billing.creditos_usd", nomes)
        self.assertIn("ia.billing.gasto_mes_usd", nomes)
        self.assertIn("claude.orcamento_restante_usd", nomes)
        pares = {c.args[0]: c.args[1] for c in mock_gauge.call_args_list}
        self.assertEqual(pares["ia.billing.creditos_usd"], 0.0)
        self.assertEqual(pares["ia.billing.gasto_mes_usd"], 3.44)

    @patch("core.claude_billing.consultar_custo_mes_console")
    def test_sincronizar_saldo_real_zera_quando_gasto_atinge_pack(self, mock_consulta):
        o.aplicar_saldo_console(2.41, gasto_mes_usd=3.44, emitir_datadog=False)
        mock_consulta.return_value = {"ok": True, "gasto_mes_usd": 5.85, "fonte": "console_api"}
        out = o.sincronizar_saldo_real(emitir_datadog=False)
        self.assertTrue(out["ok"])
        self.assertAlmostEqual(out["creditos_usd"], 0.0, places=2)
        self.assertAlmostEqual(out["resumo"]["restante_usd"], 0.0, places=2)

    @patch.object(o, "_talvez_alertar")
    def test_aplicar_zero_inativa_toggle(self, _alerta):
        from core import claude_toggle as tog

        with patch.object(tog, "_cfg_env_ativo", return_value=True):
            o.aplicar_saldo_console(0.0, emitir_datadog=False)
            ok, motivo = tog.claude_esta_ativo()
        self.assertFalse(ok)
        self.assertIn("sem_credito", motivo)

    @patch.object(o, "_talvez_alertar")
    def test_aplicar_painel_reativa_mesmo_com_env_off(self, _alerta):
        from core import claude_toggle as tog

        tog.inativar_por_saldo()
        with patch.object(tog, "_cfg_env_ativo", return_value=False):
            o.aplicar_saldo_console(4.0, emitir_datadog=False, fonte_saldo="console_painel")
            ok, _ = tog.claude_esta_ativo()
        self.assertTrue(ok)

    @patch.object(o, "_talvez_alertar")
    def test_cost_api_positiva_reativa(self, _alerta):
        from core import claude_toggle as tog

        tog.inativar_por_saldo()
        with patch.object(tog, "_cfg_env_ativo", return_value=True):
            o.aplicar_saldo_console(8.57, gasto_mes_usd=0.4, emitir_datadog=False, fonte_saldo="console_api")
            ok, _ = tog.claude_esta_ativo()
        self.assertTrue(ok)

    @patch("core.claude_billing.sondar_credito_disponivel", return_value={"ok": True, "com_credito": True, "motivo": "ok"})
    def test_sonda_sucesso_religa(self, _sonda):
        from core import claude_toggle as tog

        tog.inativar_por_saldo()
        with patch.object(tog, "_cfg_env_ativo", return_value=False):
            out = o.talvez_sondar_saldo(ignorar_intervalo=True)
            ok, _ = tog.claude_esta_ativo()
        self.assertTrue(out.get("sondou"))
        self.assertTrue(out.get("com_credito"))
        self.assertTrue(ok)

    @patch("core.datadog_metrics.gauge")
    def test_marcar_saldo_zerado_nao_apaga_snapshot_acima_de_2(self, mock_gauge):
        o.aplicar_saldo_console(8.99, gasto_mes_usd=0.4, emitir_datadog=False, fonte_saldo="console_painel")
        r = o.marcar_saldo_zerado_console(motivo="api_credit_too_low")
        self.assertGreaterEqual(float(r["restante_usd"]), 2.0)
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("claude.orcamento_restante_usd", nomes)
        pares = {c.args[0]: c.args[1] for c in mock_gauge.call_args_list}
        self.assertGreaterEqual(pares["claude.orcamento_restante_usd"], 2.0)

    @patch("core.datadog_metrics.gauge")
    def test_marcar_saldo_zerado_quando_snapshot_ja_e_zero(self, _gauge):
        o.aplicar_saldo_console(0.0, emitir_datadog=False, fonte_saldo="console_api")
        r = o.marcar_saldo_zerado_console(motivo="api_credit_too_low")
        self.assertAlmostEqual(float(r["restante_usd"]), 0.0, places=2)

    @patch("core.claude_billing.consultar_custo_mes_console")
    def test_sincronizar_nao_inventa_teto_8_99(self, mock_consulta):
        mock_consulta.return_value = {"ok": True, "gasto_mes_usd": 1.0, "fonte": "console_api"}
        out = o.sincronizar_saldo_real(emitir_datadog=False)
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "sem_snapshot_console")
        self.assertIsNone(o.carregar_estado().get("saldo_console_usd"))
        self.assertNotIn("creditos_usd", out)

    @patch("core.claude_billing.consultar_custo_mes_console")
    def test_env_ancora_saldo_e_nao_reseta_no_mesmo_valor(self, mock_consulta):
        mock_consulta.return_value = {"ok": False, "motivo": "sem_admin_api_key"}
        with patch.dict("os.environ", {"CLAUDE_SALDO_CONSOLE_USD": "5"}, clear=False):
            out1 = o.sincronizar_saldo_real(emitir_datadog=False)
            self.assertTrue(out1.get("ancora_env"))
            self.assertAlmostEqual(out1["resumo"]["restante_usd"], 5.0, places=2)
            with patch.object(o, "_talvez_alertar"):
                o.registrar_uso(
                    modelo="claude-haiku-4-5",
                    input_tokens=100_000,
                    output_tokens=0,
                    origem="teste",
                )
            resto_apos_uso = o.resumo()["restante_usd"]
            self.assertLess(resto_apos_uso, 5.0)
            out2 = o.sincronizar_saldo_real(emitir_datadog=False)
            self.assertFalse(out2.get("ancora_env"))
            self.assertAlmostEqual(out2["resumo"]["restante_usd"], resto_apos_uso, places=4)

    def test_carregar_estado_nao_sobrescreve_snapshot_sem_fonte(self):
        self.path.write_text(
            '{"orcamento_usd": 5.0, "consumido_usd": 0, "saldo_console_usd": 5.0,'
            ' "gasto_mes_console_usd": 0,'
            ' "resultados": {"ok": 0, "falha": 0, "fallback": 0, "vazio": 0, "bloqueado": 0},'
            ' "por_origem": {}, "por_modelo": {}}',
            encoding="utf-8",
        )
        with patch.object(o, "_cfg") as cfg:
            cfg.return_value.CLAUDE_ORCAMENTO_USD = 8.99
            e = o.carregar_estado()
        self.assertAlmostEqual(float(e["orcamento_usd"]), 5.0, places=2)


if __name__ == "__main__":
    unittest.main()
