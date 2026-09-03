"""tests/test_agente_monitor_buybox.py"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.ml import agente_monitor_buybox as ag


class TestAgenteMonitorBuybox(unittest.TestCase):
    def test_pula_sem_catalog_product_id(self):
        lista = [{"id": "x", "ativo": True, "nome": "sem catálogo"}]
        with patch.object(ag, "_carregar_lista", return_value=lista):
            out = ag.executar()
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_catalogos"], 0)

    @patch.object(ag, "analisar_estabilidade_vencedor", return_value={"ok": False})
    @patch.object(
        ag,
        "registrar_snapshot_buybox",
        return_value={
            "vencedor_atual": {
                "seller_id": "3365946217",
                "preco": 28.90,
                "posicao_na_lista": 0,
            }
        },
    )
    @patch.object(ag, "consultar_ofertas_catalogo", return_value=[{"seller_id": "3365946217"}])
    def test_log_vencedor(self, *_):
        lista = [{"id": "kit", "ativo": True, "catalog_product_id": "MLB41490081"}]
        with patch.object(ag, "_carregar_lista", return_value=lista):
            out = ag.executar()
        self.assertEqual(out["total_catalogos"], 1)
        self.assertIn("3365946217", out["resumos"][0])
        self.assertIn("28,90", out["resumos"][0])


if __name__ == "__main__":
    unittest.main()
