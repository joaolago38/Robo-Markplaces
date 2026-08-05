"""
tests/test_agente_leilao_veiculo.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.leilao import agente_leilao_veiculo as agente


class TestAgenteLeilaoVeiculo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "ROOT")
    def test_sem_veiculos_ativos(self, mock_root):
        mock_root.__truediv__ = lambda _s, rel: self.tmp_path / rel
        catalogo = self.tmp_path / "catalogo" / "leiloes_veiculos_monitorados.json"
        catalogo.parent.mkdir(parents=True)
        catalogo.write_text("[]", encoding="utf-8")
        with patch.object(agente, "LEILAO_VEICULOS_CATALOGO", "catalogo/leiloes_veiculos_monitorados.json"), patch.object(
            agente, "LEILAO_BUSCA_TODOS_VEICULOS", False
        ):
            out = agente.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_veiculos"], 0)

    @patch.object(agente, "obter_lotes_diretos", return_value={})
    @patch.object(agente, "obter_lotes_sumare", return_value=([], {"lotes_veiculo": 0}))
    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "buscar_veiculo_em_fontes")
    @patch.object(agente, "_carregar_veiculos")
    def test_alerta_todos_achados_novos(self, mock_veiculos, mock_busca, mock_alertar, _sumare, _diretos):
        mock_veiculos.return_value = [
            {"id": "v1", "ativo": True, "marca": "Fiat", "modelo": "Uno", "ano_min": 2010, "ano_max": 2015}
        ]
        item_base = {
            "hash": "abc123",
            "url": "https://copart.com.br/1",
            "titulo": "Fiat Uno 2012 leilão Campinas/SP",
            "snippet": "lance R$ 9.800,00",
            "fonte_nome": "Copart",
            "fonte_id": "copart",
            "fonte_tipo": "leiloeiro",
            "marca": "Fiat",
            "modelo": "Uno",
            "ano": 2012,
            "valor": "R$ 9.800,00",
            "cidade": "Campinas",
            "uf": "SP",
        }
        mock_busca.return_value = {"achados": [item_base], "diagnostico": {"ddg_brutos": 1}}

        def _analisar(_veiculo, achados):
            return [{**item_base, "lance_brl": 9800.0, "vantajoso": False, "analise_fipe": {"motivo": "FIPE n/d"}}]

        with patch.object(agente, "LEILAO_BUSCA_TODOS_VEICULOS", False), patch.object(
            agente, "LEILAO_ALERTAR_TODOS_ACHADOS", True
        ), patch.object(agente, "_analisar_achados", side_effect=_analisar), patch.object(
            agente, "HISTORY_PATH", self.tmp_path / "hist.json"
        ), patch.object(agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"), patch.object(
            agente, "LEILAO_ALERTA_RESUMO", False
        ), patch.object(agente, "LEILAO_IA_AVALIAR_PARAMETROS", False):
            out1 = agente.executar(enviar_alerta=True)
            out2 = agente.executar(enviar_alerta=True)

        self.assertTrue(out1["ok"])
        self.assertEqual(out1["com_novos"], 1)
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("veículos encontrados", msg)
        self.assertIn("R$ 9.800,00", msg)
        self.assertEqual(out2["com_novos"], 0)

    @patch.object(agente, "obter_lotes_diretos", return_value={})
    @patch.object(agente, "obter_lotes_sumare", return_value=([], {"lotes_veiculo": 0}))
    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "buscar_veiculo_em_fontes")
    def test_modo_busca_todos_veiculos(self, mock_busca, mock_alertar, _sumare, _diretos):
        mock_busca.return_value = {"achados": [], "diagnostico": {}}
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"
        ), patch.object(agente, "LEILAO_BUSCA_TODOS_VEICULOS", True), patch.object(
            agente, "LEILAO_ALERTA_RESUMO", False
        ), patch.object(agente, "LEILAO_IA_AVALIAR_PARAMETROS", False), patch.object(
            agente, "_analisar_achados", return_value=[]
        ):
            out = agente.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_veiculos"], 1)
        veiculo_passado = mock_busca.call_args[0][0]
        self.assertTrue(veiculo_passado.get("busca_todos"))

    def test_montar_alerta_detran(self):
        msg = agente._montar_alerta(
            [
                {
                    "veiculo": "Honda Civic",
                    "prioridade": 1,
                    "novos_vantajosos": [
                        {
                            "fonte_tipo": "detran",
                            "fonte_nome": "DETRAN Paraná",
                            "uf": "PR",
                            "cidade": "Curitiba",
                            "marca": "Honda",
                            "modelo": "Civic",
                            "ano": 2016,
                            "valor": "R$ 25.000,00",
                            "lance_brl": 25000.0,
                            "custo_total_brl": 27500.0,
                            "comissao_leiloeiro_brl": 1250.0,
                            "valor_fipe": 55000.0,
                            "modelo_fipe": "Civic LXR",
                            "margem_fipe_reais": 27500.0,
                            "margem_fipe_pct": 50.0,
                            "vantajoso": True,
                            "data_leilao": "20/08/2026",
                            "url_cadastro": "https://www.detran.pr.gov.br/leilao-de-veiculos",
                            "titulo": "Civic leilão",
                            "url": "https://detran.pr.gov.br/x",
                            "url_anuncio": "https://detran.pr.gov.br/x",
                        }
                    ],
                }
            ]
        )
        self.assertIn("vantagem FIPE", msg)
        self.assertIn("Curitiba — DETRAN Paraná", msg)
        self.assertIn("Honda Civic 2016", msg)
        self.assertIn("FIPE", msg)
        self.assertIn("+50%", msg)
        self.assertIn("Top", msg)

    def test_montar_resumo_varredura(self):
        diag = {
            "ddg_queries": 10,
            "ddg_brutos": 4,
            "ddg_descartados_filtro": 2,
            "ddg_detran_queries": 2,
            "ddg_detran_brutos": 0,
            "ddg_status": "vazio",
            "ddg_nota": "DDG respondeu vazio em todas as queries",
            "sumare_achados": 1,
            "sumare_candidatos": 5,
            "sumare_detran_candidatos": 2,
            "sumare_detran_achados": 0,
            "meta_fontes": {"leiloeiros_na_rodada": 5, "detrans_na_rodada": 5, "leiloeiros_ids": ["copart"], "detrans_ufs": ["SP"]},
            "sumare_coleta": {"lotes_veiculo": 3, "leiloes_ok": 2, "leiloes_falha": 0},
        }
        with patch.object(agente, "LEILAO_INCLUIR_SUMARE_DIRETO", True):
            msg = agente._montar_resumo_varredura(
                [
                    {
                        "veiculo": "Fiat Fiorino",
                        "prioridade": 1,
                        "achados_total": 2,
                        "vantajosos_total": 1,
                        "novos": [],
                        "novos_vantajosos": [],
                    },
                    {
                        "veiculo": "VW Gol",
                        "prioridade": 2,
                        "achados_total": 0,
                        "vantajosos_total": 0,
                        "novos": [],
                        "novos_vantajosos": [],
                    },
                ],
                diagnostico_agregado=diag,
            )
        self.assertIn("resumo da varredura", msg)
        self.assertIn("FIPE", msg)
        self.assertIn("Fiorino", msg)
        self.assertIn("vantagem FIPE", msg)
        self.assertIn("Diagnóstico da coleta", msg)
        self.assertIn("Sumaré direto", msg)
        self.assertIn("DDG (vazio)", msg)
        self.assertIn("DETRAN:", msg)
        self.assertIn("Nota DDG:", msg)

        msg_off = agente._montar_resumo_varredura(
            [{"veiculo": "X", "prioridade": 1, "achados_total": 0, "vantajosos_total": 0, "novos": [], "novos_vantajosos": []}],
            diagnostico_agregado=diag,
        )
        self.assertNotIn("Sumaré direto", msg_off)

    def test_agregar_diagnostico_prioriza_status_ddg(self):
        agg = agente._agregar_diagnostico(
            [
                {"diagnostico": {"ddg_status": "ok", "ddg_queries": 1, "ddg_brutos": 0}},
                {
                    "diagnostico": {
                        "ddg_status": "breaker",
                        "ddg_nota": "breaker ativo",
                        "ddg_queries": 0,
                        "sumare_detran_achados": 1,
                    }
                },
            ]
        )
        self.assertEqual(agg["ddg_status"], "breaker")
        self.assertEqual(agg["sumare_detran_achados"], 1)
        self.assertEqual(agg["ddg_queries"], 1)

    @patch.object(agente, "obter_lotes_diretos", return_value={})
    @patch.object(agente, "obter_lotes_sumare", return_value=([], {"lotes_veiculo": 0}))
    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "buscar_veiculo_em_fontes", return_value={"achados": [], "diagnostico": {}})
    @patch.object(agente, "_carregar_veiculos")
    def test_envia_resumo_mesmo_sem_novos(self, mock_veiculos, _mock_busca, mock_alertar, _sumare, _diretos):
        mock_veiculos.return_value = [
            {"id": "v1", "ativo": True, "marca": "Fiat", "modelo": "Fiorino", "prioridade": 1}
        ]
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"
        ), patch.object(
            agente, "LEILAO_ALERTA_RESUMO", True
        ), patch.object(agente, "LEILAO_IA_AVALIAR_PARAMETROS", False), patch.object(
            agente, "_analisar_achados", return_value=[]
        ):
            out = agente.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["alerta_resumo_enviado"])
        mock_alertar.assert_called()
        self.assertIn("resumo da varredura", mock_alertar.call_args_list[-1][0][0])

    @patch.object(agente, "obter_lotes_diretos", return_value={})
    @patch.object(agente, "obter_lotes_sumare", return_value=([], {"lotes_veiculo": 0}))
    @patch.object(agente, "buscar_veiculo_em_fontes", return_value={"achados": [], "diagnostico": {}})
    @patch.object(agente, "_carregar_veiculos")
    def test_loga_ddg_quando_sem_achados(self, mock_veiculos, _mock_busca, _sumare, _diretos):
        mock_veiculos.return_value = [
            {"id": "v1", "ativo": True, "marca": "Fiat", "modelo": "Fiorino"}
        ]
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"
        ), patch.object(
            agente, "mensagem_circuit_breaker", return_value="DDG circuit breaker ativo — liberação em ~60s"
        ), patch.object(agente, "LEILAO_IA_AVALIAR_PARAMETROS", False):
            with self.assertLogs("agente_leilao_veiculo", level="WARNING") as logs:
                agente.executar(enviar_alerta=False)
        self.assertTrue(any("circuit breaker" in line for line in logs.output))

    @patch.object(agente, "obter_lotes_diretos", return_value={})
    @patch.object(agente, "obter_lotes_sumare", return_value=([], {"lotes_veiculo": 0}))
    @patch.object(agente, "buscar_veiculo_em_fontes")
    @patch.object(agente, "_carregar_veiculos")
    def test_loga_achados_com_data_e_cadastro(self, mock_veiculos, mock_busca, _sumare, _diretos):
        mock_veiculos.return_value = [
            {"id": "v1", "ativo": True, "marca": "Honda", "modelo": "Civic"}
        ]
        mock_busca.return_value = {
            "achados": [
            {
                "hash": "h1",
                "url": "https://detran.pr.gov.br/edital/1",
                "url_anuncio": "https://detran.pr.gov.br/edital/1",
                "fonte_tipo": "detran",
                "fonte_nome": "DETRAN Paraná",
                "uf": "PR",
                "cidade": "Curitiba",
                "marca": "Honda",
                "modelo": "Civic",
                "ano": 2016,
                "valor": "R$ 25.000,00",
                "data_leilao": "20/08/2026",
                "url_cadastro": "https://www.detran.pr.gov.br/leilao-de-veiculos",
            }
            ],
            "diagnostico": {},
        }
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"
        ), patch.object(
            agente, "_analisar_achados", side_effect=lambda _v, achados: achados
        ), patch.object(agente, "LEILAO_IA_AVALIAR_PARAMETROS", False):
            with self.assertLogs("agente_leilao_veiculo", level="INFO") as logs:
                agente.executar(enviar_alerta=False)
        joined = "\n".join(logs.output)
        self.assertIn("20/08/2026", joined)
        self.assertIn("leilao-de-veiculos", joined)
        self.assertIn("Curitiba", joined)

    @patch.object(agente, "_carregar_veiculos", side_effect=RuntimeError("boom"))
    def test_nunca_lanca_excecao(self, *_):
        with patch.object(agente, "LEILAO_BUSCA_TODOS_VEICULOS", False):
            out = agente.executar(enviar_alerta=False)
        self.assertFalse(out["ok"])
        self.assertIn("boom", out["erro"])


if __name__ == "__main__":
    unittest.main()
