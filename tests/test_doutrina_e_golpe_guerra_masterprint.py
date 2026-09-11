"""tests/test_doutrina_e_golpe_guerra_masterprint.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import doutrina_guerra_impala as dg_imp
from integracoes.filamentos import batalha_filamentos as bat
from integracoes.filamentos import doutrina_guerra_masterprint as dg
from integracoes.filamentos import golpe_guerra_masterprint as gg


class TestDoutrinaMasterprint(unittest.TestCase):
    def test_arquivo_tem_frente_e_branco_preco(self):
        d = dg.carregar_doutrina()
        self.assertEqual(d.get("sku_preco"), "231020002")
        self.assertEqual(d.get("cnpj"), "23811261000197")
        self.assertEqual(
            set(d.get("skus_frente") or []),
            {"231020001", "231020002", "231020003"},
        )

    def test_so_branco_mexe_preco(self):
        self.assertTrue(dg_imp.sku_pode_mexer_preco("231020002"))
        self.assertFalse(dg_imp.sku_pode_mexer_preco("231020001"))
        self.assertFalse(dg_imp.sku_pode_mexer_preco("231020003"))
        self.assertFalse(dg_imp.sku_pode_mexer_preco("231020099"))
        self.assertTrue(dg_imp.sku_pode_mexer_preco("IMP-PERL-004"))
        self.assertFalse(dg_imp.sku_pode_mexer_preco("IMP-MIMO-003"))
        self.assertTrue(dg_imp.sku_pode_mexer_preco("KIT-5"))

    def test_ignorar_sem_mlb(self):
        row = dg.classificar_golpe(
            {
                "sku": "231020002",
                "mlb_ok": False,
                "fonte_rival": "ao_vivo",
                "gap_pct": 8.0,
                "rivais_no_tam": 2,
                "nosso_preco": 74.9,
                "rival_min": 70.0,
            },
            produto={"custo_total": 45.96, "fase_atual": 1},
            doutrina=dg.carregar_doutrina(),
        )
        self.assertEqual(row["classificacao"], dg.CLASSIF_IGNORAR)
        self.assertFalse(row["disparar"])

    def test_igualar_branco_acima_do_piso(self):
        row = dg.classificar_golpe(
            {
                "sku": "231020002",
                "mlb_ok": True,
                "fonte_rival": "ao_vivo",
                "gap_pct": 8.0,
                "rivais_no_tam": 2,
                "nosso_preco": 74.9,
                "rival_min": 70.0,
            },
            produto={"custo_total": 45.96, "fase_atual": 1},
            doutrina=dg.carregar_doutrina(),
        )
        self.assertEqual(row["classificacao"], dg.CLASSIF_IGUALAR)
        self.assertTrue(row["disparar"])
        self.assertEqual(row["arma"], "preco")

    def test_nao_perseguir_abaixo_do_piso(self):
        row = dg.classificar_golpe(
            {
                "sku": "231020002",
                "mlb_ok": True,
                "fonte_rival": "ao_vivo",
                "gap_pct": 20.0,
                "rivais_no_tam": 2,
                "nosso_preco": 74.9,
                "rival_min": 40.0,
            },
            produto={"custo_total": 45.96, "fase_atual": 1},
            doutrina=dg.carregar_doutrina(),
        )
        self.assertEqual(row["classificacao"], dg.CLASSIF_NAO_PERSEGUIR)
        self.assertTrue(row["disparar"])

    def test_preto_diferencia(self):
        row = dg.classificar_golpe(
            {
                "sku": "231020001",
                "mlb_ok": True,
                "fonte_rival": "ao_vivo",
                "gap_pct": 10.0,
                "rivais_no_tam": 2,
                "nosso_preco": 79.9,
                "rival_min": 72.0,
            },
            produto={"custo_total": 45.96, "fase_atual": 1},
            doutrina=dg.carregar_doutrina(),
        )
        self.assertEqual(row["classificacao"], dg.CLASSIF_DIFERENCIAR)
        self.assertEqual(row["arma"], "listing")

    def test_publicar_ordem_frente(self):
        cond = {
            "checks": {
                "mlb_entrada": False,
                "mlb_preco": False,
                "mlb_giro": False,
                "estoque_entrada": 0,
                "reviews": 0,
            }
        }
        ok, motivo = dg.sku_pode_publicar_agora("231020001", condicoes=cond)
        self.assertTrue(ok)
        self.assertEqual(motivo, "abrir_frente_petg_preto")
        ok_b, _ = dg.sku_pode_publicar_agora("231020002", condicoes=cond)
        self.assertFalse(ok_b)

    def test_fase4_sem_repricing_impala(self):
        d = dg.carregar_doutrina()
        fase4 = next(f for f in (d.get("fases") or []) if f.get("id") == 4)
        agentes = fase4.get("agentes") or []
        self.assertNotIn("repricing_impala", agentes)
        self.assertEqual(agentes, ["golpe_guerra_masterprint"])
        self.assertTrue(
            any("repricing_impala" in str(x) for x in (d.get("nao_fazer_global") or []))
        )


class TestGolpeEBatalha(unittest.TestCase):
    def test_escolhe_igualar_branco(self):
        batalha = {
            "comparacoes": [
                {
                    "sku": "231020001",
                    "mlb_ok": True,
                    "fonte_rival": "ao_vivo",
                    "gap_pct": 12.0,
                    "rivais_no_tam": 2,
                    "nosso_preco": 79.9,
                    "rival_min": 71.0,
                    "kit_tag": "kit:preto",
                },
                {
                    "sku": "231020002",
                    "mlb_ok": True,
                    "fonte_rival": "ao_vivo",
                    "gap_pct": 8.0,
                    "rivais_no_tam": 2,
                    "nosso_preco": 74.9,
                    "rival_min": 70.0,
                    "kit_tag": "kit:branco",
                },
            ]
        }
        produtos = [
            {"sku": "231020001", "custo_total": 45.96, "fase_atual": 1},
            {"sku": "231020002", "custo_total": 45.96, "fase_atual": 1},
        ]
        out = gg.montar_golpe(batalha, produtos=produtos)
        self.assertEqual(out["cnpj"], "23811261000197")
        self.assertTrue(out["disparar"])
        self.assertEqual(out["golpe"]["sku"], "231020002")
        self.assertEqual(out["golpe"]["classificacao"], dg.CLASSIF_IGUALAR)

    def test_batalha_casa_cor_petg(self):
        anuncios = [
            {
                "item_id": "MLB1234567890",
                "titulo": "Filamento PETG 1kg Preto 1.75mm",
                "preco": 69.9,
            },
            {
                "item_id": "MLB1234567891",
                "titulo": "Filamento PETG 1kg Branco Premium",
                "preco": 71.0,
            },
        ]
        batalha = bat.montar_batalha(anuncios)
        por = {c["sku"]: c for c in batalha["comparacoes"]}
        self.assertEqual(por["231020001"]["fonte_rival"], "ao_vivo")
        self.assertEqual(por["231020001"]["rival_min"], 69.9)
        self.assertEqual(por["231020002"]["fonte_rival"], "ao_vivo")
        self.assertFalse(por["231020001"]["mlb_ok"])

    def test_processar_sem_alerta(self):
        out = bat.processar_guerra_petg(
            {"produtos": []},
            enviar_alerta=False,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["cnpj"], "23811261000197")
        self.assertFalse(out["golpe"]["disparar"])


class TestAgenteGolpeMp(unittest.TestCase):
    @patch("agentes.filamentos.agente_golpe_guerra_masterprint.GOLPE_GUERRA_MASTERPRINT_ATIVO", False)
    def test_desligado(self, *_):
        from agentes.filamentos.agente_golpe_guerra_masterprint import executar

        out = executar()
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "agente_desligado")
