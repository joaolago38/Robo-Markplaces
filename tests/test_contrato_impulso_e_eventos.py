"""tests/test_contrato_impulso_e_eventos.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core import algoritmo_eventos as ev
from integracoes.ml import contrato_impulso_ml as contrato


class TestAlgoritmoEventos(unittest.TestCase):
    def test_emite_priorizar_e_congelar(self):
        avaliacoes = {
            "mercadolivre": {
                "status": "critico",
                "score": 40,
                "metrics": {"pendencias": 20, "claims_rate": 0.02},
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

    def test_campanha_exige_link(self):
        fake = {"ok": True, "ativo": True, "skus_liberados": ["IMP-MIMO-003"], "bloqueados": []}
        ok, motivo = contrato.campanha_pode_enviar("IMP-MIMO-003", link_valido=False, contrato=fake)
        self.assertFalse(ok)
        self.assertEqual(motivo, "link_mlb_invalido")


class TestRepricingImpalaApplyPath(unittest.TestCase):
    @patch("agentes.repricing.agente_repricing_impala.deve_congelar_repricing", return_value=(False, ""))
    @patch("agentes.repricing.agente_repricing_impala.carregar_produtos_catalogo")
    def test_dry_run_nao_aplica(self, mock_cat, _cong):
        mock_cat.return_value = [
            {
                "sku": "IMP-MIMO-003",
                "nome": "Kit Impala",
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
