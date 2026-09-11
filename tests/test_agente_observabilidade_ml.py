"""tests/test_agente_observabilidade_ml.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from agentes.ml import agente_observabilidade_ml as obs


class TestObservabilidadeMl(unittest.TestCase):
    @patch("integracoes.ml.ml_product_ads.emitir_metricas_ads_hoje")
    @patch("integracoes.ml.ml_product_ads.ultima_listagem_ok", return_value=True)
    @patch("integracoes.ml.ml_product_ads.listar_campanhas", return_value=[{"id": "C1"}])
    @patch("integracoes.esmaltes.metricas_catalogo_impala.emitir_metricas_catalogo_impala")
    @patch("integracoes.ml.integridade_dados_ml.executar")
    def test_executar_emite_integridade_e_catalogo(
        self, mock_auditar, mock_cat, mock_listar, _ok, mock_ads
    ):
        mock_auditar.return_value = {"ok": True, "pct": 100.0, "timestamp": "t"}
        mock_cat.return_value = {"ok": True, "guerra_sem_mlb": 2}
        out = obs.executar(anuncios=[{"item_id": "MLB1"}])
        self.assertTrue(out["ok"])
        mock_auditar.assert_called_once_with(anuncios=[{"item_id": "MLB1"}])
        mock_cat.assert_called_once()
        mock_listar.assert_called_once_with(dias=1, emitir_visibilidade=False)
        mock_ads.assert_called_once()
        self.assertEqual(out["catalogo"]["guerra_sem_mlb"], 2)
        self.assertEqual(out["ads_hoje"]["campanhas"], 1)

    @patch("integracoes.ml.ml_product_ads.emitir_metricas_ads_hoje")
    @patch("integracoes.ml.ml_product_ads.listar_campanhas", return_value=[])
    @patch("integracoes.esmaltes.metricas_catalogo_impala.emitir_metricas_catalogo_impala")
    @patch("integracoes.ml.integridade_dados_ml.executar", side_effect=RuntimeError("ml down"))
    def test_executar_nunca_lanca(self, _auditar, mock_cat, _listar, mock_ads):
        mock_cat.return_value = {"ok": True}
        out = obs.executar()
        self.assertFalse(out["ok"])
        self.assertIn("erro_integridade", out)
        mock_cat.assert_called_once()
        mock_ads.assert_called()


if __name__ == "__main__":
    unittest.main()
