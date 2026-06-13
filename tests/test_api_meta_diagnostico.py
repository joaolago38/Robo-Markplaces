"""
tests/test_api_meta_diagnostico.py
Cobre o endpoint /meta/diagnostico.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.app import app


class TestMetaDiagnostico(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("api.app.validar_conexao_meta", return_value={"ok": False, "erro": "sem token"})
    def test_conexao_falha_502(self, *_):
        resp = self.client.get("/meta/diagnostico")
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(resp.get_json()["ok"])

    @patch("api.app.normalizar_por_plataforma", return_value={"instagram": {"gasto": 10.0, "receita": 30.0, "roas": 3.0}})
    @patch("api.app.listar_metricas_por_plataforma", return_value=[{"publisher_platform": "instagram"}])
    @patch("api.app.validar_conexao_meta", return_value={"ok": True, "usuario": "M", "conta": "C", "moeda": "BRL"})
    def test_ok_200(self, *_):
        resp = self.client.post("/meta/diagnostico", json={"periodo_dias": 7})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("instagram", body["plataformas"])

    @patch("api.app.validar_conexao_meta", return_value={"ok": True, "usuario": "M"})
    @patch("api.app.listar_metricas_por_plataforma", return_value=[])
    @patch("api.app.normalizar_por_plataforma", return_value={})
    def test_periodo_invalido_400(self, *_):
        resp = self.client.post("/meta/diagnostico", json={"periodo_dias": "abc"})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
