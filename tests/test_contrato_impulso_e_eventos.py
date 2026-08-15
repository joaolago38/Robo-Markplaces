"""tests/test_contrato_impulso_e_eventos.py"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from core import algoritmo_eventos as ev
from integracoes.ml import contrato_impulso_ml as contrato


class TestAlgoritmoEventos(unittest.TestCase):
    def test_emite_priorizar_e_congelar(self):
        avaliacoes = {
            "mercadolivre": {
                "status": "critico",
                "score": 40,
                "metrics": {"pendencias": 20, "claims_rate": 0.02, "configurado": True},
                "variacoes_relevantes": [{"metrica": "score", "variacao_pct": -8}],
                "acoes_recomendadas": [],
            }
        }
        with patch.object(ev, "ALGORITMO_EVENTOS_ATIVO", True):
            novos = ev.emitir_de_avaliacao(avaliacoes)
        tipos = {e["tipo"] for e in novos}
        self.assertIn("priorizar_chat", tipos)
        self.assertIn("congelar_repricing", tipos)
        self.assertIn("revisar_listing", tipos)

    def test_inativo_nao_emite_eventos(self):
        avaliacoes = {
            "shopee": {
                "status": "inativo",
                "score": 0,
                "metrics": {"configurado": False, "pendencias": 0, "claims_rate": 0.0},
                "variacoes_relevantes": [],
                "acoes_recomendadas": [],
            }
        }
        with patch.object(ev, "ALGORITMO_EVENTOS_ATIVO", True):
            self.assertEqual(ev.emitir_de_avaliacao(avaliacoes), [])

    def test_emitir_desligado_retorna_vazio(self):
        with patch.object(ev, "ALGORITMO_EVENTOS_ATIVO", False):
            self.assertEqual(ev.emitir_de_avaliacao({"mercadolivre": {"status": "ok", "score": 90}}), [])

    def test_persistir_listar_e_flags(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "eventos.json"
            agora = datetime.now(timezone.utc)
            novos = [
                {
                    "tipo": "congelar_repricing",
                    "marketplace": "mercadolivre",
                    "motivo": "score baixo",
                    "criado_em": agora.isoformat(),
                    "expira_em": (agora + timedelta(hours=2)).isoformat(),
                    "prioridade": 1,
                },
                {
                    "tipo": "priorizar_chat",
                    "marketplace": "mercadolivre",
                    "motivo": "pendencias",
                    "criado_em": agora.isoformat(),
                    "expira_em": (agora + timedelta(hours=2)).isoformat(),
                    "prioridade": 2,
                },
                {
                    "tipo": "congelar_repricing",
                    "marketplace": "mercadolivre",
                    "motivo": "duplicado",
                    "criado_em": agora.isoformat(),
                    "expira_em": (agora + timedelta(hours=2)).isoformat(),
                    "prioridade": 3,
                },
                {
                    "tipo": "congelar_repricing",
                    "marketplace": "shopee",
                    "motivo": "outro mp",
                    "criado_em": agora.isoformat(),
                    "expira_em": (agora - timedelta(hours=1)).isoformat(),
                    "prioridade": 1,
                },
            ]
            with patch.object(ev, "EVENTOS_PATH", path):
                merged = ev.persistir_eventos(novos)
                self.assertEqual(len(merged), 2)
                self.assertTrue(ev.tem_evento("congelar_repricing"))
                cong, motivo = ev.deve_congelar_repricing()
                self.assertTrue(cong)
                self.assertIn("score", motivo)
                ok_chat, _ = ev.deve_priorizar_chat()
                self.assertTrue(ok_chat)
                self.assertEqual(ev.listar_ativos(tipo="revisar_listing"), [])
                sem, _ = ev.deve_congelar_repricing("amazon")
                self.assertFalse(sem)


class TestContratoImpulso(unittest.TestCase):
    def test_fail_closed_sem_mlb(self):
        fake = {
            "ok": True,
            "ativo": True,
            "skus_liberados": [],
            "bloqueados": [
                {"sku": "IMP-MIMO-003", "bloqueios": ["sem_mlb"], "pode_impulsionar": False}
            ],
            "liberados": [],
        }
        ok, motivo = contrato.sku_pode_impulsionar("IMP-MIMO-003", contrato=fake)
        self.assertFalse(ok)
        self.assertIn("bloqueado", motivo)

    def test_liberado(self):
        fake = {
            "ok": True,
            "ativo": True,
            "skus_liberados": ["IMP-BAIL-005"],
            "bloqueados": [],
            "liberados": [{"sku": "IMP-BAIL-005"}],
        }
        ok, motivo = contrato.sku_pode_impulsionar("IMP-BAIL-005", contrato=fake)
        self.assertTrue(ok)
        self.assertEqual(motivo, "liberado_guerra")

    def test_ads_sem_liberados(self):
        fake = {"ok": True, "ativo": True, "skus_liberados": []}
        ok, motivo = contrato.ads_pode_ligar(contrato=fake)
        self.assertFalse(ok)
        self.assertIn("nenhum_sku", motivo)

    def test_ads_com_liberados_e_desligado(self):
        self.assertTrue(contrato.ads_pode_ligar(contrato={"ok": True, "ativo": True, "skus_liberados": ["X"]})[0])
        self.assertEqual(
            contrato.ads_pode_ligar(contrato={"ok": True, "ativo": False})[1],
            "contrato_desligado",
        )

    def test_campanha_exige_link(self):
        fake = {"ok": True, "ativo": True, "skus_liberados": ["IMP-MIMO-003"], "bloqueados": []}
        ok, motivo = contrato.campanha_pode_enviar("IMP-MIMO-003", link_valido=False, contrato=fake)
        self.assertFalse(ok)
        self.assertEqual(motivo, "link_mlb_invalido")

    def test_campanha_ok_e_fora_guerra(self):
        fake = {"ok": True, "ativo": True, "skus_liberados": ["IMP-MIMO-003"], "bloqueados": []}
        self.assertTrue(
            contrato.campanha_pode_enviar("IMP-MIMO-003", link_valido=True, contrato=fake)[0]
        )
        ok, motivo = contrato.campanha_pode_enviar("OUTRO", link_valido=True, contrato=fake)
        self.assertFalse(ok)
        self.assertEqual(motivo, "fora_skus_guerra")

    def test_sku_vazio_e_contrato_desligado(self):
        fake = {"ok": True, "ativo": True, "skus_liberados": []}
        self.assertEqual(contrato.sku_pode_impulsionar("", contrato=fake)[1], "sku_vazio")
        with patch.object(contrato, "_produto_por_sku", return_value={"sku": "X", "canais": {}}):
            with patch.object(contrato, "identidade_ml_ok", return_value=True):
                ok, motivo = contrato.sku_pode_impulsionar("X", contrato={"ativo": False})
                self.assertTrue(ok)
                self.assertEqual(motivo, "contrato_desligado_mlb_ok")
        with patch.object(contrato, "_produto_por_sku", return_value=None):
            ok, motivo = contrato.sku_pode_impulsionar("Y", contrato={"ativo": False})
            self.assertFalse(ok)
            self.assertEqual(motivo, "contrato_desligado_sem_mlb")

    def test_identidade_e_produto_por_sku(self):
        self.assertFalse(contrato.identidade_ml_ok(None))
        with patch.object(contrato, "_mlb_valido", return_value=True):
            with patch.object(contrato, "_item_id_ml", return_value="MLB123456789"):
                self.assertTrue(contrato.identidade_ml_ok({"sku": "A"}))
        produtos = [{"sku": "imp-mimo-003"}, {"sku": "OUTRO"}]
        self.assertEqual(contrato._produto_por_sku("IMP-MIMO-003", produtos)["sku"], "imp-mimo-003")
        self.assertIsNone(contrato._produto_por_sku("", produtos))
        self.assertIsNone(contrato._produto_por_sku("ZZZ", produtos))

    def test_montar_contrato_desligado(self):
        with patch.object(contrato, "CONTRATO_IMPULSO_ML_ATIVO", False):
            out = contrato.montar_contrato()
        self.assertTrue(out["ok"])
        self.assertFalse(out["ativo"])
        self.assertEqual(out["motivo"], "contrato_desligado")

    def test_montar_contrato_usa_snapshot_decisao(self):
        status_snap = [
            {"sku": "IMP-ATAC-010", "pode_impulsionar": True, "item_id": "MLB111222333"},
        ]
        snap = {
            "skus_guerra": status_snap,
            "fazer": {"acao": "publicar"},
            "nao_fazer": {"acao": "ads"},
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "contrato.json"
            with patch.object(contrato, "CONTRATO_IMPULSO_ML_ATIVO", True):
                with patch.object(contrato, "carregar_produtos_catalogo", return_value=[]):
                    with patch.object(contrato, "carregar_skus_guerra", return_value=[]):
                        with patch.object(contrato, "avaliar_skus_guerra", return_value=[]):
                            with patch.object(contrato, "ler_json", return_value=snap):
                                with patch.object(contrato, "CONTRATO_PATH", path):
                                    with patch.object(contrato, "_mlb_valido", return_value=True):
                                        out = contrato.montar_contrato()
        self.assertTrue(out["fonte_decisao"])
        self.assertEqual(out["skus_liberados"], ["IMP-ATAC-010"])
        self.assertEqual(out["fazer"], {"acao": "publicar"})

    def test_montar_contrato_ativo_persiste(self):
        status = [
            {
                "sku": "IMP-BAIL-005",
                "pode_impulsionar": True,
                "item_id": "MLB987654321",
            },
            {
                "sku": "IMP-MIMO-003",
                "pode_impulsionar": False,
                "bloqueios": ["sem_mlb"],
                "item_id": "",
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "contrato.json"
            with patch.object(contrato, "CONTRATO_IMPULSO_ML_ATIVO", True):
                with patch.object(contrato, "carregar_produtos_catalogo", return_value=[]):
                    with patch.object(contrato, "carregar_skus_guerra", return_value=[]):
                        with patch.object(contrato, "avaliar_skus_guerra", return_value=status):
                            with patch.object(contrato, "ler_json", return_value={}):
                                with patch.object(contrato, "CONTRATO_PATH", path):
                                    with patch.object(contrato, "_mlb_valido", side_effect=lambda x: bool(x)):
                                        out = contrato.montar_contrato(forcar_recalculo=True)
            self.assertTrue(out["ativo"])
            self.assertEqual(out["skus_liberados"], ["IMP-BAIL-005"])
            self.assertEqual(out["item_ids_liberados"], ["MLB987654321"])
            self.assertEqual(len(out["bloqueados"]), 1)
            self.assertTrue(path.exists())

    def test_carregar_contrato_usa_cache_e_refresh(self):
        cached = {"ok": True, "timestamp": "2026-01-01T00:00:00+00:00", "ativo": True}
        with patch.object(contrato, "ler_json", return_value=cached):
            self.assertIs(contrato.carregar_contrato(), cached)
        with patch.object(contrato, "montar_contrato", return_value={"ok": True, "ativo": False}) as mock_m:
            out = contrato.carregar_contrato(refresh=True)
            self.assertFalse(out["ativo"])
            mock_m.assert_called_once()

    def test_listar_item_ids(self):
        ids = contrato.listar_item_ids_para_otimizacao(
            contrato={"item_ids_liberados": ["MLB1", "", "MLB2"]}
        )
        self.assertEqual(ids, ["MLB1", "MLB2"])


class TestRepricingImpalaApplyPath(unittest.TestCase):
    @patch("agentes.repricing.agente_repricing_impala.deve_congelar_repricing", return_value=(False, ""))
    @patch("agentes.repricing.agente_repricing_impala.carregar_produtos_catalogo")
    def test_dry_run_nao_aplica(self, mock_cat, _cong):
        mock_cat.return_value = [
            {
                "sku": "IMP-PERL-004",
                "nome": "Kit Impala Perolado",
                "custo_total": 27.0,
                "fase_atual": 1,
                "preco": 30.0,
                "precos_por_fase": {"fase1": 44.9},
                "canais": {"mercadolivre": {"item_id": "MLB123456789", "preco": 30.0}},
            }
        ]
        from agentes.repricing.agente_repricing_impala import executar

        out = executar(dry_run=True)
        self.assertTrue(out.get("total_ajustes", 0) >= 1)
        self.assertEqual(out.get("total_aplicados", 0), 0)


if __name__ == "__main__":
    unittest.main()
