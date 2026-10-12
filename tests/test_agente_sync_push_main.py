"""
tests/test_agente_sync_push_main.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.orquestrador import agente_sync_push_main as sync
from agentes.orquestrador.registro_agentes import listar_agentes_push_main


class TestSyncPushMain(unittest.TestCase):
    def test_lista_mais_agentes_que_orquestrador(self):
        from agentes.orquestrador.registro_agentes import listar_agentes

        self.assertGreater(len(listar_agentes_push_main()), len(listar_agentes()))

    def test_inclui_extras_deploy(self):
        ids = {a.id for a in listar_agentes_push_main()}
        self.assertIn("renovar_tokens", ids)
        self.assertIn("relatorio", ids)

    @patch.object(sync, "executar_ciclo", return_value={"ok": True, "falhas": 0})
    def test_executar_chama_ciclo_completo(self, mock_ciclo):
        out = sync.executar(enviar_resumo_telegram=True)
        self.assertTrue(out["ok"])
        mock_ciclo.assert_called_once()
        kwargs = mock_ciclo.call_args.kwargs
        self.assertEqual(kwargs["prefixo_metrica"], "push_main")
        self.assertIn("Push main", kwargs["titulo_resumo"])

    @patch.object(sync, "executar", return_value={"ok": True, "falhas": 0})
    def test_main_ok(self, *_):
        self.assertEqual(sync.main(), 0)

    @patch.object(sync, "executar", return_value={"ok": False, "falhas": 2})
    def test_main_com_falhas(self, *_):
        self.assertEqual(sync.main(), 1)


if __name__ == "__main__":
    unittest.main()
