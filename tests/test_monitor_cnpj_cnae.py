"""tests/test_monitor_cnpj_cnae.py"""
from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from core.horario import agora_brasil
from integracoes.empresa import monitor_ml_cnpj as mon_ml
from integracoes.empresa import vinculo_cnae_cnpj_produtos as vinculo


class TestVinculoCnaeCnpj(unittest.TestCase):
    def test_resolver_cnae_esmaltes(self):
        lista = vinculo.resolver_por_cnae("4772-5/00")
        self.assertTrue(any(e.get("id") == "esmaltes_impala" for e in lista))
        self.assertTrue(any(e.get("cnpj") == "52668583000127" for e in lista))

    def test_resolver_cnae_masterprint(self):
        lista = vinculo.resolver_por_cnae("4751-2/01")
        self.assertTrue(any(e.get("id") == "masterprint" for e in lista))
        self.assertTrue(any(e.get("cnpj") == "23811261000197" for e in lista))

    def test_montar_vinculo_por_cnpj(self):
        out = vinculo.montar_vinculo(cnpj="52668583000127")
        self.assertTrue(out["ok"])
        self.assertEqual(out["total"], 1)
        v = out["vinculos"][0]
        self.assertEqual(v["cnpj"], "52668583000127")
        self.assertTrue(v["marketplaces"]["prioriza_mercadolivre"])
        self.assertIn("mercadolivre", v["marketplaces"]["ativos"])
        self.assertIn("abertos_para_expansao", v["marketplaces"])
        self.assertIn("fingerprint", v)
        self.assertIn("produtos", v)

    def test_montar_vinculo_por_cnae(self):
        out = vinculo.montar_vinculo(cnae="4772-5/00")
        self.assertGreaterEqual(out["total"], 1)
        self.assertTrue(any(v["cnpj"] == "52668583000127" for v in out["vinculos"]))

    def test_detectar_alteracao_primeira_vez(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snap = root / "snap.json"
            mon = root / "mon.json"
            with patch.object(vinculo, "SNAPSHOT_PATH", snap), patch.object(
                vinculo, "MONITORADOS_PATH", mon
            ), patch.object(vinculo, "HISTORY_PATH", root / "hist.json"):
                base = vinculo.montar_vinculo(cnpj="23811261000197")
                mudancas = vinculo.detectar_alteracoes(base["vinculos"])
                self.assertEqual(len(mudancas), 1)
                self.assertEqual(mudancas[0]["motivo"], "primeira_verificacao")
                mon_data = vinculo.carregar_monitorados()
                self.assertIn("23811261000197", mon_data.get("cnpjs") or {})

                vinculo.salvar_snapshot({**base, "alteracoes": mudancas, "gerado_em": "t"})
                mudancas2 = vinculo.detectar_alteracoes(base["vinculos"])
                self.assertEqual(mudancas2, [])


class TestMonitorMlCnpj(unittest.TestCase):
    def test_devido_por_alteracao(self):
        self.assertTrue(
            mon_ml.cnpj_devido_monitor_ml({"ativo": True}, forcar_alteracao=True)
        )

    def test_devido_ciclo_10_dias(self):
        antigo = (agora_brasil() - timedelta(days=11)).isoformat()
        self.assertTrue(
            mon_ml.cnpj_devido_monitor_ml(
                {"ativo": True, "ultima_monitorizacao_ml": antigo},
                intervalo_dias=10,
            )
        )
        recente = (agora_brasil() - timedelta(days=2)).isoformat()
        self.assertFalse(
            mon_ml.cnpj_devido_monitor_ml(
                {"ativo": True, "ultima_monitorizacao_ml": recente},
                intervalo_dias=10,
            )
        )

    def test_acoes_decisao_perguntas(self):
        acoes = mon_ml._acoes_decisao(
            {"produtos": {"total_skus": 5}, "agentes_prioritarios": ["esmaltes_operacao"]},
            {"perguntas_pendentes": 3, "anuncios_a_melhorar_total": 2},
            {"nivel": "atencao"},
        )
        self.assertEqual(acoes["urgencia"], "media")
        self.assertTrue(any("pergunta" in f.lower() for f in acoes["fazer"]))

    @patch("integracoes.empresa.monitor_ml_cnpj.coletar_subsidio_ml")
    def test_ciclo_dispara_na_alteracao(self, mock_sub):
        mock_sub.return_value = {
            "ok": True,
            "cnpj": "52668583000127",
            "cnpj_formatado": "52.668.583/0001-27",
            "acoes": {"fazer": ["x"], "nao_fazer": [], "custo": [], "urgencia": "baixa"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            mon_path = Path(tmp) / "mon.json"
            with patch(
                "integracoes.empresa.vinculo_cnae_cnpj_produtos.MONITORADOS_PATH",
                mon_path,
            ):
                base = vinculo.montar_vinculo(cnpj="52668583000127")
                alt = [
                    {
                        "cnpj": "52668583000127",
                        "motivo": "fingerprint_alterado",
                        "deltas": ["SKUs"],
                    }
                ]
                ciclo = mon_ml.montar_ciclo_monitor_ml(
                    base["vinculos"], alt, ao_vivo=False, intervalo_dias=10
                )
                self.assertEqual(ciclo["total_monitorados_ml"], 1)
                mock_sub.assert_called_once()
                data = vinculo.carregar_monitorados()
                reg = (data.get("cnpjs") or {}).get("52668583000127") or {}
                self.assertTrue(reg.get("monitoramento_ml_ativo"))


class TestAgenteMonitorCnpjCnae(unittest.TestCase):
    def test_mensagem_decisao(self):
        from agentes.empresa.agente_monitor_cnpj_cnae import montar_mensagem

        msg = montar_mensagem(
            {
                "total": 1,
                "filtro": {},
                "alteracoes": [
                    {
                        "nome_fantasia": "Impala",
                        "cnpj_formatado": "52.668.583/0001-27",
                        "motivo": "fingerprint_alterado",
                        "deltas": ["SKUs vinculados: 1 → 2"],
                    }
                ],
                "vinculos": [],
                "dono_produtos_global": {
                    "cnpj_formatado": "52.668.583/0001-27",
                    "usando_alvo": False,
                    "cnpj_alvo": "23811261000197",
                },
                "ciclo_ml": {
                    "intervalo_dias": 10,
                    "total_monitorados_ml": 1,
                    "subsidios": [
                        {
                            "empresa_id": "esmaltes_impala",
                            "cnpj_formatado": "52.668.583/0001-27",
                            "motivo_ciclo": "alteracao:fingerprint_alterado",
                            "acoes": {
                                "fazer": ["Responder *2* pergunta(s) pendente(s) no ML"],
                                "nao_fazer": ["Não migrar dono sem checklist"],
                                "custo": ["Portfólio: *10* SKUs"],
                                "urgencia": "media",
                            },
                            "resumo_conta": {
                                "ok": True,
                                "anuncios_ativos": 12,
                                "anuncios_a_melhorar_total": 2,
                                "perguntas_pendentes": 2,
                                "pos_venda_claims": 0,
                                "reputacao": "Verde",
                                "a_melhorar_top": [],
                            },
                            "estado_ml": {"nivel": "atencao", "alertas": []},
                            "vinculo_resumo": {
                                "cnae_principal": "4772-5/00",
                                "total_skus": 10,
                                "eh_dono": True,
                                "agentes_prioritarios": ["esmaltes_operacao"],
                                "marketplaces_abertos": ["shopee"],
                            },
                        }
                    ],
                },
            }
        )
        self.assertIn("AGIR AGORA", msg)
        self.assertIn("PANORAMA ML", msg)
        self.assertIn("PRÓXIMOS PASSOS", msg)
        self.assertIn("10 dias", msg)
        self.assertIn("52.668.583/0001-27", msg)
        self.assertIn("pergunta", msg.lower())

    @patch("agentes.empresa.agente_monitor_cnpj_cnae.montar_ciclo_monitor_ml")
    @patch("agentes.empresa.agente_monitor_cnpj_cnae.gestor_telegram_configurado", return_value=False)
    @patch("agentes.empresa.agente_monitor_cnpj_cnae.salvar_snapshot")
    @patch("agentes.empresa.agente_monitor_cnpj_cnae.detectar_alteracoes", return_value=[])
    def test_executar_ok(self, _det, _save, _tg, mock_ciclo):
        from agentes.empresa import agente_monitor_cnpj_cnae as ag

        mock_ciclo.return_value = {
            "intervalo_dias": 10,
            "total_monitorados_ml": 0,
            "subsidios": [],
        }
        with patch.object(ag, "escrever_json_atomico"):
            out = ag.executar(cnpj="52668583000127", enviar_alerta=False, ml_ao_vivo=False)
        self.assertTrue(out["ok"])
        self.assertIn("mensagem", out)
        self.assertIn("ciclo_ml", out)
        self.assertGreaterEqual(out["total"], 1)


if __name__ == "__main__":
    unittest.main()
