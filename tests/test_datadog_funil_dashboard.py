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
            "robo.impala.batalha.seller_vendas_dia",
            "robo.impala.batalha.seller_anuncios",
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
            "robo.ml.integridade.pct",
            "robo.vendas.receita_bruta",
            "robo.ml.loja.p0.tem",
            "robo.ml.loja.p0.telegram_ok",
            "robo.ml.loja.p0.telegram_skip",
            "robo.ml.loja.p0.chat_falhas",
            "robo.ml.saude.anuncios_ativos_conta",
            "robo.ml.integridade.ids_busca",
            "robo.ml.integridade.paging_total",
            "robo.ml.saude.conta_ok",
            "robo.meta.ciclo.pronto",
        ):
            self.assertIn(metric, blob, msg=metric)
        self.assertEqual(grupo["id"], dd.GROUP_SAUDE_CONTA_ML_ID)

    def test_grupo_pontos_cegos_tem_p0_loja(self):
        grupo = dd._grupo_pontos_cegos()
        blob = str(grupo)
        self.assertIn("robo.ml.loja.p0.tem", blob)
        self.assertIn("robo.ml.loja.p0.telegram_ok", blob)
        self.assertIn("robo.ml.loja.p0.telegram_skip", blob)

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
            "robo.migracao.fase",
            "robo.migracao.bloqueada",
            "robo.migracao.impala_liberado",
            "robo.migracao.cnpj2_pode_operar",
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

    def test_grupo_decisao_guerra_titulo_atracao(self):
        grupo = dd._grupo_decisao_guerra_impala()
        blob = str(grupo)
        for metric in (
            "robo.impala.guerra.fase",
            "robo.impala.guerra.publicar_agora",
            "robo.impala.guerra.titulo_atracao",
            "robo.impala.guerra.carmed_titulo",
            "robo.impala.guerra.nosso_carmed",
            "robo.esmaltes.kit_manicure.entrada_ok",
            "robo.impala.guerra.canal_liberado{marketplace:mercadolivre}",
            "robo.impala.guerra.canal_liberado{marketplace:shopee}",
            "robo.impala.guerra.canal_liberado{marketplace:magalu}",
            "robo.impala.guerra.canal_liberado{marketplace:amazon}",
            "robo.cruzeiro.mercado.seller_vendas_dia",
            "robo.cruzeiro.mercado.seller_anuncios",
            "robo.meta.ciclo.pronto",
            "robo.meta.ciclo.saude_conta_ok",
            "robo.meta.ciclo.impala_ok",
            "robo.meta.campanhas_total",
            "robo.meta.campanhas_plataforma{plataforma:instagram}",
            "robo.meta.campanhas_plataforma{plataforma:facebook}",
        ):
            self.assertIn(metric, blob, msg=metric)

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

    def test_monitor_integridade_ml(self):
        nomes = [m["name"] for m in dd._monitores_desejados()]
        self.assertTrue(any("Integridade dados ML" in n for n in nomes))

    def test_monitor_oscilacao(self):
        nomes = [m["name"] for m in dd._monitores_desejados()]
        self.assertTrue(any("Oscilacao Datadog" in n for n in nomes))

    def test_monitor_magalu_query_pega_magazine_luiza_e_http_400(self):
        src = Path(dd.__file__).read_text(encoding="utf-8")
        self.assertIn("Magazine Luiza", src)
        self.assertIn("401 OR 400 OR invalid_grant", src)

    def test_grupo_progresso_24m(self):
        grupo = dd._grupo_progresso_24m()
        blob = str(grupo)
        for metric in (
            "robo.progresso.lucro_mes_impala",
            "robo.progresso.meta_lucro_ano1_mes",
            "robo.progresso.meta_lucro_alvo_mes",
            "robo.progresso.cruzeiro_unid_dia",
            "robo.progresso.meta_cruzeiro_unid_dia",
        ):
            self.assertIn(metric, blob, msg=metric)
        self.assertNotIn("robo.progresso.lucro_mes_masterprint", blob)
        self.assertNotIn("robo.progresso.petg_unid_dia", blob)
        self.assertEqual(grupo["id"], dd.GROUP_PROGRESSO_24M_ID)
        self.assertIn("[Fase 1 / Impala]", blob)
        self.assertIn("query1 / query2 * 100", blob)

    def test_grupo_progresso_fase2_masterprint(self):
        grupo = dd._grupo_progresso_fase2_masterprint()
        blob = str(grupo)
        for metric in (
            "robo.progresso.lucro_mes_masterprint",
            "robo.progresso.petg_unid_dia",
            "robo.progresso.meta_petg_unid_dia",
        ):
            self.assertIn(metric, blob, msg=metric)
        self.assertNotIn("robo.progresso.lucro_mes_impala", blob)
        self.assertNotIn("robo.progresso.cruzeiro_unid_dia", blob)
        self.assertEqual(grupo["id"], dd.GROUP_PROGRESSO_FASE2_ID)
        self.assertIn("[Fase 2 / Masterprint]", blob)

    def test_grupo_mercado_masterprint_seller_vendas_dia(self):
        grupo = dd._grupo_mercado_masterprint()
        blob = str(grupo)
        self.assertIn("robo.masterprint_petg.seller_vendas_dia", blob)
        self.assertIn("robo.filamentos.ml.masterprint.seller_vendas_dia", blob)
        self.assertIn("funil.unidades_7d", blob)


if __name__ == "__main__":
    unittest.main()
