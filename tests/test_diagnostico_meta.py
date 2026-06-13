"""
tests/test_diagnostico_meta.py
Cobre o diagnóstico de conexão Meta (executar + impressão + main).
"""
import importlib.util
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import integracoes.meta.meta_ads_client as mac  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "diagnostico_meta", os.path.join(ROOT, "scripts", "diagnostico_meta.py")
)
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)


class TestExecutar(unittest.TestCase):
    @patch.object(mac, "validar_conexao", return_value={"ok": False, "erro": "sem token"})
    def test_conexao_falha(self, *_):
        out = diag.executar()
        self.assertFalse(out["ok"])
        self.assertEqual(out["erro"], "sem token")

    @patch.object(mac, "validar_conexao", return_value={"ok": True, "usuario": "Maria", "conta": "C", "moeda": "BRL"})
    @patch.object(mac, "listar_metricas_campanhas", return_value=[
        {"campaign_id": "1", "spend": "100", "actions": [], "action_values": [{"action_type": "purchase", "value": "300"}]},
    ])
    @patch.object(mac, "listar_metricas_por_plataforma", return_value=[
        {"publisher_platform": "instagram", "spend": "100", "actions": [], "action_values": [{"action_type": "purchase", "value": "300"}]},
    ])
    def test_ok_completo(self, *_):
        out = diag.executar(periodo_dias=7)
        self.assertTrue(out["ok"])
        self.assertEqual(out["etapas"]["campanhas"]["total"], 1)
        self.assertEqual(out["etapas"]["campanhas"]["gasto_total"], 100.0)
        self.assertEqual(out["etapas"]["campanhas"]["roas_geral"], 3.0)
        self.assertIn("instagram", out["etapas"]["plataformas"])

    @patch.object(mac, "validar_conexao", return_value={"ok": True, "usuario": "M", "conta": "C", "moeda": "BRL"})
    @patch.object(mac, "listar_metricas_campanhas", return_value=[])
    @patch.object(mac, "listar_metricas_por_plataforma", return_value=[])
    def test_ok_sem_campanhas(self, *_):
        out = diag.executar()
        self.assertTrue(out["ok"])
        self.assertEqual(out["etapas"]["campanhas"]["roas_geral"], 0.0)


class TestImprimir(unittest.TestCase):
    def test_imprime_conexao_falha(self):
        diag._imprimir({"etapas": {"conexao": {"ok": False, "erro": "x"}}})

    def test_imprime_ok_com_plataformas(self):
        diag._imprimir({
            "ok": True,
            "etapas": {
                "conexao": {"ok": True, "usuario": "M", "conta": "C", "moeda": "BRL"},
                "campanhas": {"total": 2, "gasto_total": 10, "receita_total": 30, "roas_geral": 3.0},
                "plataformas": {"instagram": {"gasto": 10.0, "receita": 30.0, "roas": 3.0}},
            },
        })

    def test_imprime_ok_sem_plataformas(self):
        diag._imprimir({
            "ok": True,
            "etapas": {
                "conexao": {"ok": True, "usuario": "M", "conta": "C", "moeda": "BRL"},
                "campanhas": {"total": 0, "gasto_total": 0, "receita_total": 0, "roas_geral": 0.0},
                "plataformas": {},
            },
        })


class TestMain(unittest.TestCase):
    @patch.object(diag, "executar", return_value={"ok": True, "etapas": {"conexao": {"ok": True}, "campanhas": {}, "plataformas": {}}})
    def test_main_ok(self, *_):
        self.assertEqual(diag.main([]), 0)

    @patch.object(diag, "executar", return_value={"ok": False, "etapas": {"conexao": {"ok": False, "erro": "x"}}})
    def test_main_falha(self, *_):
        self.assertEqual(diag.main(["7"]), 1)

    @patch.object(diag, "executar", return_value={"ok": True, "etapas": {"conexao": {"ok": True}, "campanhas": {}, "plataformas": {}}})
    def test_main_arg_invalido(self, *_):
        self.assertEqual(diag.main(["abc"]), 0)


if __name__ == "__main__":
    unittest.main()
