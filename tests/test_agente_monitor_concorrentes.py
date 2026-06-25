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


if __name__ == "__main__":
    unittest.main()
