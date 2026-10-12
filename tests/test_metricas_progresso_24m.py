"""tests/test_metricas_progresso_24m.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.esmaltes import metricas_progresso_24m as p


class TestMetricasProgresso24m(unittest.TestCase):
    def test_classificar_cnpj_sku(self):
        self.assertEqual(p.classificar_cnpj_sku("IMP-MIMO-F1"), "impala")
        self.assertEqual(p.classificar_cnpj_sku("BUNDLE-X"), "impala")
        self.assertEqual(p.classificar_cnpj_sku("CRZ-KIT-003"), "impala")
        self.assertEqual(p.classificar_cnpj_sku("PETG-1KG"), "masterprint")
        self.assertEqual(p.classificar_cnpj_sku(""), "masterprint")

    def test_prefixo_emite_petg(self):
        self.assertTrue(p.prefixo_emite_petg("masterprint_petg"))
        self.assertFalse(p.prefixo_emite_petg("filamentos.ml"))
        self.assertFalse(p.prefixo_emite_petg("pref"))
        self.assertFalse(p.prefixo_emite_petg("impala.ml"))

    @patch("integracoes.esmaltes.metricas_progresso_24m.gauge")
    def test_emitir_metas(self, mock_g):
        p.emitir_metas_progresso_24m()
        nomes = [c.args[0] for c in mock_g.call_args_list]
        self.assertIn("progresso.meta_lucro_ano1_mes", nomes)
        self.assertIn("progresso.meta_lucro_alvo_mes", nomes)
        self.assertIn("progresso.meta_cruzeiro_unid_dia", nomes)
        self.assertIn("progresso.meta_petg_unid_dia", nomes)
        self.assertIn("progresso.meta_reviews", nomes)
        vals = {c.args[0]: c.args[1] for c in mock_g.call_args_list}
        self.assertEqual(vals["progresso.meta_lucro_ano1_mes"], 2500.0)
        self.assertEqual(vals["progresso.meta_lucro_alvo_mes"], 20000.0)
        self.assertEqual(vals["progresso.meta_cruzeiro_unid_dia"], 12.0)
        self.assertEqual(vals["progresso.meta_petg_unid_dia"], 6.0)

    @patch("integracoes.esmaltes.metricas_progresso_24m.gauge")
    def test_emitir_realizado_dois_cnpjs(self, mock_g):
        analise = {
            "lucro_reais": 40.0,
            "linhas": [
                {"sku": "IMP-MIMO-F1", "lucro_reais": 8.69, "quantidade": 1},
                {"sku": "CRZ-KIT-003", "lucro_reais": 28.17, "quantidade": 2},
                {"sku": "PETG-1KG", "lucro_reais": 3.14, "quantidade": 1},
            ],
        }
        p.emitir_realizado_vendas(analise, dias=2)
        vals = {c.args[0]: c.args[1] for c in mock_g.call_args_list}
        self.assertEqual(vals["progresso.janela_dias"], 2.0)
        self.assertEqual(vals["progresso.lucro_janela"], 40.0)
        self.assertEqual(vals["progresso.lucro_mes_estimado"], 600.0)
        # Impala = 8.69 + 28.17 = 36.86 → ×15 = 552.9
        self.assertEqual(vals["progresso.lucro_mes_impala"], 552.9)
        self.assertEqual(vals["progresso.lucro_mes_masterprint"], 47.1)
        self.assertEqual(vals["progresso.cruzeiro_unid_dia"], 1.0)
        tags_por_nome = {
            c.args[0]: (c.kwargs.get("tags") or []) for c in mock_g.call_args_list
        }
        self.assertIn("marca:impala", tags_por_nome["progresso.lucro_mes_impala"])
        self.assertIn("fase:1", tags_por_nome["progresso.lucro_mes_impala"])
        self.assertIn("marca:masterprint", tags_por_nome["progresso.lucro_mes_masterprint"])
        self.assertIn("fase:2", tags_por_nome["progresso.lucro_mes_masterprint"])

    @patch("integracoes.esmaltes.metricas_progresso_24m.gauge")
    def test_emitir_realizado_zero(self, mock_g):
        p.emitir_realizado_vendas({"lucro_reais": 0, "linhas": []}, dias=2)
        vals = {c.args[0]: c.args[1] for c in mock_g.call_args_list}
        self.assertEqual(vals["progresso.lucro_mes_estimado"], 0.0)
        self.assertEqual(vals["progresso.cruzeiro_unid_dia"], 0.0)

    @patch("integracoes.esmaltes.metricas_progresso_24m.gauge")
    def test_emitir_petg_funil(self, mock_g):
        p.emitir_petg_funil(14)
        vals = {c.args[0]: c.args[1] for c in mock_g.call_args_list}
        self.assertEqual(vals["progresso.petg_unid_dia"], 2.0)
        self.assertNotIn("progresso.meta_petg_unid_dia", vals)

    @patch("integracoes.esmaltes.metricas_progresso_24m.gauge")
    def test_emitir_realizado_ignora_linha_sem_sku(self, mock_g):
        p.emitir_realizado_vendas(
            {
                "lucro_reais": 8.69,
                "linhas": [
                    "lixo",
                    {"sku": "", "lucro_reais": 1, "quantidade": 1},
                    {"sku": "IMP-MIMO-F1", "lucro_reais": 8.69, "quantidade": 1},
                ],
            },
            dias=1,
        )
        vals = {c.args[0]: c.args[1] for c in mock_g.call_args_list}
        self.assertEqual(vals["progresso.lucro_mes_impala"], 260.7)

    @patch("integracoes.esmaltes.metricas_progresso_24m.gauge", side_effect=RuntimeError("boom"))
    def test_emitir_nao_lanca(self, _mock_g):
        p.emitir_realizado_vendas({"lucro_reais": 1, "linhas": []}, dias=2)
        p.emitir_petg_funil(7)


if __name__ == "__main__":
    unittest.main()
