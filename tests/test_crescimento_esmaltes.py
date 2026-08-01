"""tests/test_crescimento_esmaltes.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import crescimento_esmaltes as cre


class TestCrescimentoEsmaltes(unittest.TestCase):
    def test_anexar_combo_idempotente(self):
        t1 = cre.anexar_combo_oferta("Oferta kit Impala")
        self.assertIn("removedor", t1.lower())
        t2 = cre.anexar_combo_oferta(t1)
        self.assertEqual(t1, t2)

    def test_kits_catalogo_sem_mlb(self):
        produtos = [
            {
                "sku": "IMP-KIT-001",
                "nome": "Kit 3 Impala",
                "canais": {"mercadolivre": {"ativo": True, "item_id": "MLB_PREENCHER"}},
            },
            {
                "sku": "IMP-KIT-002",
                "nome": "Kit 5 Impala",
                "canais": {"mercadolivre": {"ativo": True, "item_id": "MLB123456789"}},
            },
            {
                "sku": "AVULSO-1",
                "nome": "Esmalte avulso",
                "canais": {"mercadolivre": {"ativo": True, "item_id": "MLB_PREENCHER"}},
            },
        ]
        sem = cre.listar_kits_catalogo_sem_mlb(produtos)
        self.assertEqual(len(sem), 1)
        self.assertEqual(sem[0]["sku"], "IMP-KIT-001")

    def test_kpis_kits_pct(self):
        produtos = [
            {"sku": "IMP-KIT-001", "nome": "Kit 3", "canais": {}},
            {"sku": "AVULSO", "nome": "Avulso", "canais": {}},
        ]
        margem = {
            "analise": {
                "receita_bruta": 100.0,
                "margem_media_pct": 20.0,
                "total_itens": 2,
            },
            "linhas": [
                {"sku": "IMP-KIT-001", "receita_bruta": 60.0},
                {"sku": "AVULSO", "receita_bruta": 40.0},
            ],
        }
        kpis = cre.calcular_kpis(
            margem_snap=margem, produtos=produtos, meta_kits_pct=40.0, meta_margem_pct=15.0
        )
        self.assertEqual(kpis["kits_pct_receita"], 60.0)
        self.assertTrue(kpis["kits_meta_ok"])
        self.assertTrue(kpis["margem_meta_ok"])

    def test_checklist_prioridades(self):
        check = cre.montar_checklist(
            sem_mlb=[{"sku": "X"}],
            sugeridos=[],
            canais={"whatsapp_ok": False, "instagram_ok": True, "pendentes": ["whatsapp"]},
            kpis={"sem_vendas_periodo": True},
        )
        ids = [c["id"] for c in check]
        self.assertIn("publicar_kits_mlb", ids)
        self.assertIn("config_whatsapp", ids)

    def test_sugeridos_pendentes(self):
        montar = {
            "cruzamento": {
                "kits_sugeridos": [
                    {
                        "nome_sugerido": "Kit 3 Branco Paraiso",
                        "cores": [{"nome_cor": "Branco"}, {"nome_cor": "Paraiso"}],
                        "preco_sugerido_faixa": "R$ 40–50",
                    }
                ]
            }
        }
        pend = cre.listar_kits_sugeridos_pendentes(montar=montar, produtos=[])
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0]["motivo"], "sem_anuncio_no_catalogo")


class TestAgenteCrescimento(unittest.TestCase):
    @patch("agentes.esmaltes.agente_crescimento_esmaltes.alertar_gestor", return_value=True)
    @patch(
        "agentes.esmaltes.agente_crescimento_esmaltes.gestor_telegram_configurado",
        return_value=True,
    )
    @patch(
        "agentes.esmaltes.agente_crescimento_esmaltes.pode_alertar_esmaltes",
        return_value=(True, "ok"),
    )
    @patch("agentes.esmaltes.agente_crescimento_esmaltes.escrever_json_atomico")
    @patch("agentes.esmaltes.agente_crescimento_esmaltes.ler_json", return_value={"rodadas": []})
    @patch("agentes.esmaltes.agente_crescimento_esmaltes.montar_relatorio")
    def test_executar_ok(self, mock_rel, _ler, _write, _pode, _gestor, _alerta):
        mock_rel.return_value = {
            "ok": True,
            "timestamp": "2026-08-01T12:00:00+00:00",
            "critico": True,
            "kits_sem_mlb": [{"sku": "IMP-1"}],
            "kits_sugeridos_pendentes": [],
            "kpis": {"kits_pct_receita": None, "sem_vendas_periodo": True},
            "canais": {"whatsapp_ok": False},
            "checklist": [{"id": "publicar_kits_mlb"}],
            "resumo": {"kits_sem_mlb": 1},
            "score_ecossistema": 68.9,
        }
        from agentes.esmaltes.agente_crescimento_esmaltes import executar

        out = executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["alerta_enviado"])
        self.assertTrue(out["critico"])


if __name__ == "__main__":
    unittest.main()
