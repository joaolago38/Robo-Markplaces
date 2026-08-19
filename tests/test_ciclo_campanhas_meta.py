"""tests/test_ciclo_campanhas_meta.py — gate IG/FB no ciclo."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.meta import ciclo_campanhas as ciclo


def _cond(fase: int, ads: bool, proximo: str = "") -> dict:
    return {
        "fase": fase,
        "liberar": {"ads": ads},
        "proximo": proximo or f"aguardar_fase_3_atual_{fase}",
    }


class CicloCampanhasMetaTests(unittest.TestCase):
    def test_bloqueia_sem_impala_ads(self):
        out = ciclo.avaliar_momento_ciclo_meta(
            condicoes=_cond(0, False, "Publicar MIMO"),
            resumo_conta={"ok": True, "cor": "Verde", "atraso_rate": 0, "claims_rate": 0},
        )
        self.assertFalse(out["pronto"])
        self.assertTrue(out["saude_conta_ok"])
        self.assertFalse(out["impala_ok"])
        self.assertIn("Publicar MIMO", out["motivo"])

    def test_bloqueia_conta_laranja(self):
        out = ciclo.avaliar_momento_ciclo_meta(
            condicoes=_cond(3, True),
            resumo_conta={
                "ok": True,
                "cor": "Laranja",
                "atraso_rate": 0,
                "cancelamentos_rate": 0,
                "claims_rate": 0,
            },
        )
        self.assertFalse(out["pronto"])
        self.assertFalse(out["saude_conta_ok"])
        self.assertTrue(out["impala_ok"])
        self.assertIn("saude_conta", out["motivo"])

    def test_bloqueia_claims_altos(self):
        out = ciclo.avaliar_momento_ciclo_meta(
            condicoes=_cond(3, True),
            resumo_conta={"ok": True, "cor": "Verde", "claims_rate": 0.08},
        )
        self.assertFalse(out["pronto"])
        self.assertFalse(out["saude_conta_ok"])

    def test_pronto_fase3_e_saude_ok(self):
        out = ciclo.avaliar_momento_ciclo_meta(
            condicoes=_cond(3, True),
            resumo_conta={
                "ok": True,
                "cor": "Verde",
                "atraso_rate": 0.01,
                "cancelamentos_rate": 0,
                "claims_rate": 0.02,
            },
        )
        self.assertTrue(out["pronto"])
        self.assertTrue(out["saude_conta_ok"])
        self.assertTrue(out["impala_ok"])
        self.assertEqual(out["motivo"], "ligar_ig_fb")

    def test_sem_cor_passa_saude(self):
        ok, atual = ciclo.saude_conta_ml_ok({"avaliacoes": 0, "nota": 0})
        self.assertTrue(ok)
        self.assertIn("sem cor", atual.lower())

    def test_resumo_indisponivel(self):
        out = ciclo.avaliar_momento_ciclo_meta(
            condicoes=_cond(3, True),
            resumo_conta={"ok": False},
        )
        self.assertFalse(out["pronto"])
        self.assertEqual(out["motivo"], "saude_conta:resumo_indisponivel")

    @patch("integracoes.meta.ciclo_campanhas.gauge")
    def test_emite_plataformas_zero(self, mock_g):
        mom = ciclo.avaliar_momento_ciclo_meta(
            condicoes=_cond(0, False),
            resumo_conta={"ok": True, "cor": "Verde"},
        )
        ciclo.emitir_metricas_ciclo_meta(mom, plataformas={})
        pares = {(c.args[0], tuple(c.kwargs.get("tags") or [])): c.args[1] for c in mock_g.call_args_list}
        self.assertEqual(pares[("meta.ciclo.pronto", ())], 0.0)
        self.assertEqual(pares[("ml.saude.conta_ok", ())], 1.0)
        self.assertEqual(pares[("meta.campanhas_plataforma", ("plataforma:instagram",))], 0.0)
        self.assertEqual(pares[("meta.campanhas_plataforma", ("plataforma:facebook",))], 0.0)

    @patch("integracoes.meta.ciclo_campanhas.gauge")
    def test_catalogo_nao_zera_campanhas(self, mock_g):
        mom = ciclo.avaliar_momento_ciclo_meta(
            condicoes=_cond(0, False),
            resumo_conta={"ok": True, "cor": "Verde"},
        )
        ciclo.emitir_metricas_ciclo_meta(mom)
        nomes = [c.args[0] for c in mock_g.call_args_list]
        self.assertIn("meta.ciclo.pronto", nomes)
        self.assertIn("ml.saude.conta_ok", nomes)
        self.assertNotIn("meta.campanhas_plataforma", nomes)

    @patch("integracoes.meta.ciclo_campanhas.gauge")
    def test_emite_ig_fb_quando_ha_campanha(self, mock_g):
        mom = {
            "pronto": True,
            "saude_conta_ok": True,
            "impala_ok": True,
        }
        ciclo.emitir_metricas_ciclo_meta(
            mom,
            plataformas={
                "instagram": {"campanhas": 2, "gasto": 15.5},
                "facebook": {"campanhas": 1, "gasto": 8.0},
            },
        )
        pares = {(c.args[0], tuple(c.kwargs.get("tags") or [])): c.args[1] for c in mock_g.call_args_list}
        self.assertEqual(pares[("meta.ciclo.pronto", ())], 1.0)
        self.assertEqual(pares[("meta.campanhas_plataforma", ("plataforma:instagram",))], 2.0)
        self.assertEqual(pares[("meta.gasto_plataforma", ("plataforma:facebook",))], 8.0)


class EficienciaCicloMetaTests(unittest.TestCase):
    def test_zero_sem_ads_nem_venda(self):
        out = ciclo.avaliar_eficiencia_ciclo(
            meta={"gasto_meta": 0, "impressoes": 0, "clicks": 0, "compras_pixel": 0, "receita_meta_pixel": 0},
            ml={"ok": True, "receita_ml": 0, "pedidos_ml": 0},
        )
        self.assertEqual(out["eficiencia_pct"], 0.0)
        self.assertEqual(out["conversao_imp_pct"], 0.0)
        self.assertEqual(out["cpa_ml"], 0.0)
        self.assertEqual(out["status"], "insuficiente_dados")

    def test_roas_real_e_conversao_ponta_a_ponta(self):
        out = ciclo.avaliar_eficiencia_ciclo(
            meta={
                "gasto_meta": 50,
                "impressoes": 10000,
                "clicks": 200,
                "compras_pixel": 8,
                "receita_meta_pixel": 180,
            },
            ml={"ok": True, "receita_ml": 150, "pedidos_ml": 3},
            periodo_dias=1,
        )
        self.assertEqual(out["roas_real"], 3.0)
        self.assertEqual(out["cpa_ml"], round(50 / 3, 2))
        self.assertEqual(out["ticket_ml"], 50.0)
        self.assertEqual(out["conversao_imp_pct"], 0.03)
        self.assertEqual(out["conversao_click_pct"], 1.5)
        self.assertGreaterEqual(out["eficiencia_pct"], 100.0)
        self.assertEqual(out["status"], "sustentavel")

    def test_clicks_via_cpc(self):
        n = ciclo.clicks_de_campanha({"gasto": 40, "cpc": 2, "impressoes": 0, "ctr": 0})
        self.assertEqual(n, 20.0)

    def test_agregar_campanhas(self):
        out = ciclo.agregar_meta_campanhas(
            [
                {"metricas": {"gasto": 10, "impressoes": 1000, "cpc": 1, "compras": 1, "receita": 20, "ctr": 1}},
                {"gasto": 10, "impressoes": 1000, "cpc": 1, "compras": 1, "receita": 30, "ctr": 1},
            ]
        )
        self.assertEqual(out["gasto_meta"], 20.0)
        self.assertEqual(out["impressoes"], 2000)
        self.assertEqual(out["clicks"], 20.0)

    @patch("integracoes.meta.ciclo_campanhas.gauge")
    def test_emite_eficiencia(self, mock_g):
        efic = ciclo.avaliar_eficiencia_ciclo(
            meta={"gasto_meta": 0, "impressoes": 0, "clicks": 0, "compras_pixel": 0, "receita_meta_pixel": 0},
            ml={"ok": True, "receita_ml": 0, "pedidos_ml": 0},
        )
        ciclo.emitir_metricas_ciclo_meta(
            {"pronto": False, "saude_conta_ok": True, "impala_ok": False},
            eficiencia=efic,
        )
        nomes = [c.args[0] for c in mock_g.call_args_list]
        self.assertIn("meta.ciclo.roas_real", nomes)
        self.assertIn("meta.ciclo.conversao_imp_pct", nomes)
        self.assertIn("meta.ciclo.eficiencia_pct", nomes)


if __name__ == "__main__":
    unittest.main()
