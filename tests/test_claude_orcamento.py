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
        self.patcher = patch.object(o, "USO_PATH", self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    @patch.object(o, "_talvez_alertar")
    def test_registrar_e_restante(self, _alerta):
        with patch.object(o, "_cfg") as cfg:
            cfg.return_value.CLAUDE_ORCAMENTO_USD = 8.99
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
        r = o.resumo()
        self.assertAlmostEqual(r["consumido_usd"], 1.0, places=4)
        self.assertAlmostEqual(r["restante_usd"], 7.99, places=4)
        self.assertIn("agentes.teste", r["por_origem"])

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


if __name__ == "__main__":
    unittest.main()
