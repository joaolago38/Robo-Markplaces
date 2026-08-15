"""tests/test_datadog_funil_dashboard.py — widgets funil no script Datadog."""
from __future__ import annotations

import unittest
from pathlib import Path

from scripts import completar_datadog_saude as dd


class DatadogFunilDashboardTests(unittest.TestCase):
    def test_grupo_funil_tem_metricas_chave(self):
        grupo = dd._grupo_funil_demanda_masterprint()
        blob = str(grupo)
        for metric in (
            "robo.masterprint_petg.funil.visitas_7d",
            "robo.masterprint_petg.funil.unidades_7d",
            "robo.masterprint_petg.funil.conversao_pct",
            "robo.masterprint_petg.funil.acoes_criticas",
            "robo.filamentos.ml.funil.visitas_7d",
            "robo.filamentos.ml.funil.acoes_criticas",
            "robo.masterprint_petg.blindspot.vendas_api",
            "robo.filamentos.ml.rivais.visitas_amostra",
            "robo.masterprint_petg.blindspot.cegos",
            "robo.filamentos.ml.blindspot.cegos",
            "robo.ml.busca.sites_search_403",
            "robo.filamentos.ml.funil.acao.baixar_preco_ou_listing",
        ):
            self.assertIn(metric, blob, msg=metric)
        self.assertEqual(grupo["id"], dd.GROUP_MP_FUNIL_ID)

    def test_batalha_tem_agir_e_conversao(self):
        grupo = dd._grupo_batalha_impala()
        blob = str(grupo)
        for metric in (
            "robo.impala.batalha.agir_preco",
            "robo.impala.batalha.agir_listing",
            "robo.impala.batalha.agir_criticas",
            "robo.mercado.gap_preco_pct",
            "robo.conversao_manicures.leads_novos",
            "robo.conversao_manicures.escrita_pronta",
            "robo.conversao_manicures.roas_real",
        ):
            self.assertIn(metric, blob, msg=metric)

    def test_impala_tem_ads_probe(self):
        # Grupo Impala é montado por função que precisa de helpers; busca no source
        src = Path(dd.__file__).read_text(encoding="utf-8")
        self.assertIn("robo.ads.probe_falha", src)

    def test_monitor_funil_nas_desejadas(self):
        nomes = [m["name"] for m in dd._monitores_desejados()]
        self.assertTrue(any("Funil ML" in n for n in nomes))

    def test_monitores_cnae_e_ponto_ruptura(self):
        nomes = [m["name"] for m in dd._monitores_desejados()]
        self.assertTrue(any("CNAE segundo CNPJ" in n for n in nomes))
        self.assertTrue(any("Ponto ruptura — Impala aproximando" in n for n in nomes))
        self.assertTrue(any("segundo CNPJ liberado" in n for n in nomes))
        self.assertTrue(any("outra marca de esmalte liberada" in n for n in nomes))
        grupo = dd._grupo_ponto_ruptura_cnae()
        blob = str(grupo)
        for metric in (
            "robo.cnae_preparacao.gaps",
            "robo.cnae_preparacao.seller_masterprint",
            "robo.cnae_preparacao.pronto",
            "robo.ponto_ruptura.liberado",
            "robo.ponto_ruptura.aproximando",
            "robo.ponto_ruptura.progresso_pct",
            "robo.ponto_ruptura.avaliacoes",
            "robo.ruptura.impala.saude_score",
            "robo.ruptura.impala.produtos_seguros",
            "robo.ruptura.impala.margem_media_segura_pct",
            "robo.ruptura.impala.esforco_faltando",
            "robo.decisao.oscilacao",
            "robo.ruptura.impala.claude_assertividade_maxima",
        ):
            self.assertIn(metric, blob, msg=metric)
        self.assertEqual(grupo["id"], dd.GROUP_PONTO_RUPTURA_ID)

    def test_grupo_saude_conta_ml(self):
        grupo = dd._grupo_saude_conta_ml()
        blob = str(grupo)
        for metric in (
            "robo.ml.saude.vendas_completadas",
            "robo.ml.saude.avaliacoes",
            "robo.ml.saude.nota",
            "robo.ml.saude.claims_rate_pct",
            "robo.ml.saude.anuncios_ativos",
            "robo.ml.saude.todos_pausados",
            "robo.ml.saude.anuncios_ignorados_fora_foco",
            "robo.ml.saude.catalogo_foco_vazio",
            "robo.vendas.receita_bruta",
            "robo.ads.acos_atual",
        ):
            self.assertIn(metric, blob, msg=metric)
        self.assertEqual(grupo["id"], dd.GROUP_SAUDE_CONTA_ML_ID)

    def test_grupo_ruptura_outra_marca(self):
        grupo = dd._grupo_ruptura_outra_marca()
        blob = str(grupo)
        for metric in (
            "robo.marca_esmalte.ruptura.liberado",
            "robo.marca_esmalte.ruptura.aproximando",
            "robo.marca_esmalte.ruptura.progresso_pct",
            "robo.marca_esmalte.ruptura.radar_cego",
            "robo.marca_esmalte.ruptura.anuncios_foco",
            "robo.marca_esmalte.cnpj_canal{marketplace:mercadolivre}",
            "robo.marca_esmalte.cnpj_canal{marketplace:shopee}",
            "robo.marca_esmalte.cnpj_canal{marketplace:magalu}",
            "robo.marca_esmalte.cnpj_canal{marketplace:amazon}",
            "robo.marca_esmalte.candidata.score{*} by {marca}",
        ):
            self.assertIn(metric, blob, msg=metric)
        self.assertEqual(grupo["id"], dd.GROUP_RUPTURA_OUTRA_MARCA_ID)
        self.assertIn("52.668.583/0001-27", blob)

    def test_grupo_marca_kit_tendencia(self):
        grupo = dd._grupo_marca_kit_tendencia()
        blob = str(grupo)
        for metric in (
            "robo.esmaltes.marca_kit.total",
            "robo.esmaltes.marca_kit.boas_performance",
            "robo.esmaltes.marca_kit.score{*} by {marca}",
            "robo.esmaltes.marca_kit.score{*} by {kit}",
        ):
            self.assertIn(metric, blob, msg=metric)
        self.assertEqual(grupo["id"], dd.GROUP_MARCA_KIT_TENDENCIA_ID)

    def test_grupo_kits_manicure(self):
        grupo = dd._grupo_kits_manicure_impala()
        blob = str(grupo)
        for metric in (
            "robo.esmaltes.kit_manicure.total",
            "robo.esmaltes.kit_manicure.condicao_ok",
            "robo.esmaltes.kit_manicure.economia_media_pct",
            "robo.esmaltes.kit_manicure.indice_compra{*} by {kit}",
            "robo.esmaltes.kit_manicure.economia_pct{*} by {kit}",
        ):
            self.assertIn(metric, blob, msg=metric)
        self.assertEqual(grupo["id"], dd.GROUP_KITS_MANICURE_ID)

    def test_grupo_decisao_oscilacao(self):
        grupo = dd._grupo_decisao_oscilacao()
        blob = str(grupo)
        for metric in (
            "robo.decisao.oscilacao",
            "robo.decisao.cuidado",
            "robo.claude.ciclo.fase_maxima",
            "robo.claude.ciclo.exposto_datadog",
            "robo.vigia_datadog.saudavel",
        ):
            self.assertIn(metric, blob, msg=metric)
        self.assertEqual(grupo["id"], dd.GROUP_DECISAO_OSCILACAO_ID)
        fmts = grupo["definition"]["widgets"][0]["definition"]["requests"][0]["conditional_formats"]
        self.assertEqual(fmts[0]["palette"], "white_on_red")
        self.assertEqual(fmts[0]["comparator"], ">")

    def test_qv_saude_baixa_fica_vermelha(self):
        w = dd._qv(
            "Saude",
            "avg:robo.ruptura.impala.saude_score{*}",
            red_lt=40,
            yellow_lt=70,
            green_gt=70,
        )
        fmts = w["definition"]["requests"][0]["conditional_formats"]
        self.assertEqual(fmts[0], {"comparator": "<", "palette": "white_on_red", "value": 40})
        self.assertFalse(
            any(f.get("comparator") == ">=" and f.get("value") == 0 for f in fmts)
        )

    def test_monitor_oscilacao(self):
        nomes = [m["name"] for m in dd._monitores_desejados()]
        self.assertTrue(any("Oscilacao Datadog" in n for n in nomes))


if __name__ == "__main__":
    unittest.main()
