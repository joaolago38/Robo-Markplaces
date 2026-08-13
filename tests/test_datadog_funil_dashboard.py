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


if __name__ == "__main__":
    unittest.main()
