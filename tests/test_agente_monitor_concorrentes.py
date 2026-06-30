"""
tests/test_agente_monitor_concorrentes.py
"""
import importlib.util
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "agente_monitor_concorrentes",
    os.path.join(ROOT, "agentes", "ml", "agente_monitor_concorrentes.py"),
)
mon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mon)


_LISTA_ALERTA = [
    {
        "id": "kit1",
        "ativo": True,
        "nome": "Kit Teste",
        "termo_busca": "kit impala",
        "meu_preco": 50.0,
        "limite_resultados": 5,
    }
]

_LISTA_ESTAVEL = [
    {
        "id": "kit1",
        "ativo": True,
        "nome": "Kit Teste",
        "termo_busca": "kit impala",
        "meu_preco": 38.0,
        "limite_resultados": 5,
    }
]


class TestMonitorConcorrentes(unittest.TestCase):
    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(mon, "_carregar_lista", return_value=_LISTA_ALERTA)
    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[
        {"item_id": "MLB2", "titulo": "Conc", "preco": 40.0, "quantidade_vendida": 1},
    ])
    def test_alerta_preco_acima(self, *_):
        out = mon.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["total_alertas"], 1)
        self.assertTrue(out["enviado"])

    @patch.object(mon, "alertar_gestor")
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "_carregar_historico", return_value={"kit1": {"menor_preco": 40.0}})
    @patch.object(mon, "_carregar_lista", return_value=_LISTA_ESTAVEL)
    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[
        {"item_id": "MLB2", "titulo": "Conc", "preco": 40.0},
    ])
    def test_sem_alerta_quando_estavel(
        self,
        mock_buscar,
        mock_carregar_lista,
        mock_carregar_historico,
        mock_salvar_historico,
        mock_alertar,
    ):
        out = mon.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_alertas"], 0)
        mock_alertar.assert_not_called()
        mock_buscar.assert_called_once()

    @patch.object(mon, "_carregar_lista", return_value=[])
    def test_lista_vazia(self, *_):
        out = mon.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_monitorados"], 0)


class TestMonitorConcorrentesMetricasDatadog(unittest.TestCase):
    """Garante que as métricas são enviadas ao Datadog a cada ciclo do agente."""

    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[
        {"item_id": "MLB1", "titulo": "X", "preco": 38.0, "quantidade_vendida": 5},
        {"item_id": "MLB2", "titulo": "Y", "preco": 42.0, "quantidade_vendida": 2},
    ])
    @patch.object(mon, "_carregar_lista", return_value=[_LISTA_ESTAVEL[0]])
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "alertar_gestor", return_value=False)
    @patch.object(mon, "gauge")
    @patch.object(mon, "incrementar")
    def test_gauge_preco_e_gap_emitidos(self, mock_incrementar, mock_gauge, *_):
        mon.executar(enviar_alerta=False)

        nomes_gauge = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("mercado.meu_preco", nomes_gauge)
        self.assertIn("mercado.menor_preco_concorrente", nomes_gauge)
        self.assertIn("mercado.gap_preco_pct", nomes_gauge)
        self.assertIn("mercado.total_concorrentes", nomes_gauge)

    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[
        {"item_id": "MLB1", "titulo": "X", "preco": 30.0, "quantidade_vendida": 10},
    ])
    @patch.object(mon, "_carregar_lista", return_value=[_LISTA_ALERTA[0]])
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon, "gauge")
    @patch.object(mon, "incrementar")
    def test_incrementa_alertas_quando_preco_acima(self, mock_incrementar, mock_gauge, *_):
        mon.executar(enviar_alerta=True)

        nomes_incr = [c.args[0] for c in mock_incrementar.call_args_list]
        self.assertIn("mercado.alertas_preco", nomes_incr)

    @patch.object(mon.ml_client, "buscar_concorrentes_por_termo", return_value=[
        {"item_id": "MLB1", "titulo": "X", "preco": 38.0, "quantidade_vendida": 5},
    ])
    @patch.object(mon, "_carregar_lista", return_value=[_LISTA_ESTAVEL[0]])
    @patch.object(mon, "_carregar_historico", return_value={})
    @patch.object(mon, "_salvar_historico")
    @patch.object(mon, "alertar_gestor", return_value=False)
    @patch.object(mon, "gauge")
    @patch.object(mon, "incrementar")
    def test_tag_produto_inclui_id_do_json(self, mock_incrementar, mock_gauge, *_):
        mon.executar(enviar_alerta=False)

        todas_tags = []
        for c in mock_gauge.call_args_list:
            tags = c.kwargs.get("tags") or []
            todas_tags.extend(tags)
        self.assertTrue(any("produto:kit1" in t for t in todas_tags))


if __name__ == "__main__":
    unittest.main()
