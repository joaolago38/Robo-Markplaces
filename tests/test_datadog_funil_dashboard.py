"""tests/test_datadog_funil_dashboard.py — widgets funil no script Datadog."""
from __future__ import annotations

import unittest

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
        ):
            self.assertIn(metric, blob, msg=metric)
        self.assertEqual(grupo["id"], dd.GROUP_MP_FUNIL_ID)

    def test_monitor_funil_nas_desejadas(self):
        nomes = [m["name"] for m in dd._monitores_desejados()]
        self.assertTrue(any("Funil ML" in n for n in nomes))


if __name__ == "__main__":
    unittest.main()
