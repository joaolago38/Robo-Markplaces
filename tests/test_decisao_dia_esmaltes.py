"""tests/test_decisao_dia_esmaltes.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import decisao_dia_esmaltes as dia


class TestDecisaoDia(unittest.TestCase):
    def setUp(self):
        self.guerra = [
            {
                "sku": "IMP-MIMO-003",
                "papel": "entrada",
                "nome": "Kit 3",
                "diferencial_obrigatorio": "kit + carmed",
            },
            {
                "sku": "IMP-BAIL-005",
                "papel": "giro",
                "nome": "Kit 5",
                "diferencial_obrigatorio": "5 cores",
            },
        ]
        self.produtos = [
            {
                "sku": "IMP-MIMO-003",
                "nome": "Kit 3",
                "custo_total": 27.0,
                "preco": 44.9,
                "estoque_total": 10,
                "canais": {
                    "mercadolivre": {
                        "ativo": True,
                        "item_id": "MLB_PREENCHER",
                        "preco": 44.9,
                        "estoque": 10,
                        "taxa_canal_pct": 16,
                    }
                },
            },
            {
                "sku": "IMP-BAIL-005",
                "nome": "Kit 5",
                "custo_total": 20.0,
                "preco": 48.9,
                "estoque_total": 10,
                "canais": {
                    "mercadolivre": {
                        "ativo": True,
                        "item_id": "MLB123456789",
                        "preco": 48.9,
                        "estoque": 10,
                        "taxa_canal_pct": 16,
                    }
                },
            },
        ]

    def test_avaliar_guerra_bloqueia_sem_mlb(self):
        st = dia.avaliar_skus_guerra(
            guerra=self.guerra, produtos=self.produtos, margem_piso_pct=15.0
        )
        by_sku = {s["sku"]: s for s in st}
        self.assertFalse(by_sku["IMP-MIMO-003"]["mlb_ok"])
        self.assertFalse(by_sku["IMP-MIMO-003"]["pode_impulsionar"])
        self.assertTrue(by_sku["IMP-BAIL-005"]["mlb_ok"])
        self.assertTrue(by_sku["IMP-BAIL-005"]["pode_impulsionar"])

    def test_fazer_prioriza_mlb(self):
        st = dia.avaliar_skus_guerra(
            guerra=self.guerra, produtos=self.produtos, margem_piso_pct=15.0
        )
        fazer = dia._acao_fazer(
            guerra_status=st,
            crescimento={"canais": {"whatsapp_ok": True}, "checklist": []},
            eco_top=[],
        )
        self.assertEqual(fazer["codigo"], "preencher_mlb_guerra")
        self.assertEqual(fazer["sku"], "IMP-MIMO-003")

    def test_nao_fazer_fora_guerra(self):
        st = dia.avaliar_skus_guerra(
            guerra=self.guerra, produtos=self.produtos, margem_piso_pct=15.0
        )
        # só o kit com MLB liberado — força caminho extras
        for s in st:
            s["pode_impulsionar"] = True
            s["bloqueios"] = []
        extras = self.produtos + [
            {
                "sku": "KIT-EXTRA-99",
                "nome": "Kit Extra",
                "canais": {"mercadolivre": {"item_id": "MLB999"}},
            }
        ]
        nao = dia._acao_nao_fazer(
            guerra_status=st,
            guerra_skus={"IMP-MIMO-003", "IMP-BAIL-005"},
            produtos=extras,
        )
        self.assertEqual(nao["codigo"], "nao_abrir_sku_fora_guerra")

    def test_mensagem_tem_tres_blocos(self):
        dec = {
            "fazer": {"titulo": "A", "detalhe": "da"},
            "nao_fazer": {"titulo": "B", "detalhe": "db"},
            "custo_nao_fazer": {"titulo": "C", "detalhe": "dc"},
            "liberados": 0,
            "bloqueados": 2,
            "margem_piso_pct": 15,
            "skus_guerra": [],
            "kpis": {"sem_vendas_periodo": True},
            "regras": ["r1", "r2", "r3"],
            "evolucao": {"delta": {}},
        }
        msg = dia.montar_mensagem_telegram(dec)
        self.assertIn("FAZER", msg)
        self.assertIn("NÃO FAZER", msg)
        self.assertIn("CUSTO", msg)

    @patch("integracoes.esmaltes.decisao_dia_esmaltes.montar_relatorio")
    @patch("integracoes.esmaltes.decisao_dia_esmaltes.carregar_produtos_catalogo")
    @patch("integracoes.esmaltes.decisao_dia_esmaltes.carregar_skus_guerra")
    @patch("integracoes.esmaltes.decisao_dia_esmaltes.ler_json", return_value={})
    def test_montar_decisao(self, _ler, mock_guerra, mock_prod, mock_cre):
        mock_guerra.return_value = self.guerra
        mock_prod.return_value = self.produtos
        mock_cre.return_value = {
            "canais": {"whatsapp_ok": False},
            "checklist": [],
            "kpis": {"sem_vendas_periodo": True, "kits_pct_receita": None},
        }
        dec = dia.montar_decisao()
        self.assertTrue(dec["ok"])
        self.assertEqual(dec["fazer"]["codigo"], "preencher_mlb_guerra")
        self.assertIn("nao_fazer", dec)
        self.assertIn("custo_nao_fazer", dec)
        self.assertEqual(len(dec["skus_guerra"]), 2)


    def test_arquivo_guerra_so_kits_com_margem(self):
        guerra = dia.carregar_skus_guerra()
        skus = {str(g.get("sku") or "").upper() for g in guerra}
        self.assertEqual(skus, {"IMP-MIMO-003", "IMP-PERL-004", "IMP-JUPAES-006"})


class TestAgenteDecisao(unittest.TestCase):
    @patch("agentes.esmaltes.agente_decisao_dia_esmaltes.alertar_gestor", return_value=True)
    @patch(
        "agentes.esmaltes.agente_decisao_dia_esmaltes.gestor_telegram_configurado",
        return_value=True,
    )
    @patch(
        "agentes.esmaltes.agente_decisao_dia_esmaltes.pode_alertar_esmaltes",
        return_value=(True, "ok"),
    )
    @patch("agentes.esmaltes.agente_decisao_dia_esmaltes.escrever_json_atomico")
    @patch("agentes.esmaltes.agente_decisao_dia_esmaltes.ler_json", return_value={"rodadas": []})
    @patch("agentes.esmaltes.agente_decisao_dia_esmaltes.montar_decisao")
    def test_executar(self, mock_dec, _ler, _w, _p, _g, _a):
        mock_dec.return_value = {
            "ok": True,
            "timestamp": "2026-08-01T12:00:00+00:00",
            "fazer": {"codigo": "preencher_mlb_guerra", "titulo": "t", "detalhe": "d"},
            "nao_fazer": {"codigo": "x", "titulo": "t", "detalhe": "d"},
            "custo_nao_fazer": {"titulo": "t", "detalhe": "d"},
            "liberados": 0,
            "bloqueados": 3,
            "skus_guerra": [],
            "kpis": {"sem_vendas_periodo": True},
            "regras": ["a", "b", "c"],
            "evolucao": {"delta": {}},
            "margem_piso_pct": 15,
            "_pontos_kpi": [],
        }
        from agentes.esmaltes.agente_decisao_dia_esmaltes import executar

        out = executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["fazer"], "preencher_mlb_guerra")


if __name__ == "__main__":
    unittest.main()
