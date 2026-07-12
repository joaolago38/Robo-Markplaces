"""tests/test_monitor_concorrentes.py"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.ml import agente_monitor_concorrentes as monitor


class TestClassificarVariacao(unittest.TestCase):
    @patch("core.resumo_ia.sintetizar_claude", return_value="tendência de baixa (3ª queda seguida)")
    def test_classificacao_com_historico_suficiente(self, mock_sint):
        historico = {
            "kit1": {
                "menor_preco": 30,
                "leituras": [
                    {"menor_preco": 40},
                    {"menor_preco": 35},
                    {"menor_preco": 30},
                ],
            }
        }
        out = monitor._classificar_variacao_preco("kit1", "Kit", "termo", 28.0, historico)
        self.assertIn("tendência", out.lower())
        mock_sint.assert_called_once()

    def test_sem_historico_suficiente_retorna_none(self):
        historico = {"kit1": {"menor_preco": 30}}
        self.assertIsNone(monitor._classificar_variacao_preco("kit1", "Kit", "termo", 28.0, historico))

    @patch.object(monitor, "_classificar_variacao_preco", return_value="queda pontual")
    @patch.object(
        monitor.ml_client,
        "buscar_concorrentes_por_termo",
        return_value=[{"preco": 30, "titulo": "kit esmalte"}],
    )
    def test_alerta_inclui_classificacao(self, *_mocks):
        historico = {
            "k1": {
                "menor_preco": 40,
                "leituras": [{"menor_preco": 40}, {"menor_preco": 35}],
            }
        }
        entrada = {
            "id": "k1",
            "nome": "Prod",
            "termo_busca": "kit",
            "meu_preco": 50,
            "limite_resultados": 5,
        }
        with patch.object(monitor, "MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO", False):
            out = monitor._monitorar_entrada(entrada, historico, enriquecer_metricas=False)
        self.assertTrue(any("[queda pontual]" in a for a in out["alertas"]))

    @patch.object(monitor, "_classificar_variacao_preco", return_value=None)
    @patch.object(
        monitor.ml_client,
        "buscar_concorrentes_por_termo",
        return_value=[{"preco": 30, "titulo": "kit esmalte"}],
    )
    def test_alerta_sem_classificacao_sem_historico(self, *_mocks):
        historico = {"k1": {"menor_preco": 40}}
        entrada = {
            "id": "k1",
            "nome": "Prod",
            "termo_busca": "kit",
            "meu_preco": 50,
            "limite_resultados": 5,
        }
        with patch.object(monitor, "MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO", False):
            out = monitor._monitorar_entrada(entrada, historico, enriquecer_metricas=False)
        for a in out["alertas"]:
            self.assertNotIn("[", a)


if __name__ == "__main__":
    unittest.main()
