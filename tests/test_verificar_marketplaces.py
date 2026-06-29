"""
tests/test_verificar_marketplaces.py — script de diagnóstico de conectividade real.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scripts.verificar_marketplaces as vm


class TestTestarUm(unittest.TestCase):
    def test_nao_configurado_nao_chama_probe(self):
        probe_chamado = {"valor": False}

        def probe():
            probe_chamado["valor"] = True
            return {"ok": True, "status": 200, "msg": "autenticado"}

        out = vm._testar("mercadolivre", False, probe)
        self.assertFalse(out["configurado"])
        self.assertFalse(out["conectado"])
        self.assertFalse(probe_chamado["valor"])

    def test_configurado_e_conectado(self):
        out = vm._testar("mercadolivre", True, lambda: {"ok": True, "status": 200, "msg": "autenticado"})
        self.assertTrue(out["configurado"])
        self.assertTrue(out["conectado"])
        self.assertEqual(out["status_http"], 200)
        self.assertEqual(out["mensagem"], "autenticado")

    def test_configurado_mas_falha_real_de_conexao(self):
        """
        Este é exatamente o cenário que a versão antiga do script não
        detectava: configurado=True, mas a chamada real falhou (token
        expirado). probe_conexao() nunca lança exceção, então não
        depende de try/except para reportar isto corretamente.
        """
        out = vm._testar(
            "magalu", True, lambda: {"ok": False, "status": 401, "msg": "token expirado ou inválido"}
        )
        self.assertTrue(out["configurado"])
        self.assertFalse(out["conectado"])
        self.assertEqual(out["status_http"], 401)
        self.assertIn("expirado", out["mensagem"])


class TestMain(unittest.TestCase):
    @patch.object(vm, "probe_amazon", return_value={"ok": True, "status": 200, "msg": "autenticado"})
    @patch.object(vm, "probe_magalu", return_value={"ok": True, "status": 200, "msg": "autenticado"})
    @patch.object(vm, "probe_shopee", return_value={"ok": True, "status": 200, "msg": "autenticado"})
    @patch.object(vm, "probe_ml", return_value={"ok": False, "status": 401, "msg": "token expirado ou inválido"})
    @patch.object(vm, "_ok_config_amazon", return_value=True)
    @patch.object(vm, "_ok_config_magalu", return_value=True)
    @patch.object(vm, "_ok_config_shopee", return_value=True)
    @patch.object(vm, "_ok_config_ml", return_value=True)
    def test_resumo_reporta_falha_real_do_ml(self, *_mocks):
        exit_code = vm.main()
        self.assertEqual(exit_code, 1)  # ML falhou -> exit code != 0


if __name__ == "__main__":
    unittest.main()
