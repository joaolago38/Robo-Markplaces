"""
tests/test_agente_monitor_busca_kit_esmaltes.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.esmaltes import agente_monitor_busca_kit_esmaltes as agente


class AgenteMonitorBuscaKitEsmaltesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "resolver_fn_busca_esmaltes")
    @patch.object(agente, "_carregar_itens")
    def test_executar_conta_buscas_e_telegram(self, mock_itens, mock_resolver, mock_alertar):
        mock_itens.return_value = [
            {
                "id": "kit3-anita",
                "ativo": True,
                "marca": "anita",
                "nome": "Kit 3 Anita",
                "cor_foco": "Nude",
                "cores_busca": ["nude", "rosa"],
                "termo_busca": "kit 3 esmalte anita",
                "limite_resultados": 10,
            },
            {
                "id": "kit3-impala",
                "ativo": True,
                "marca": "impala",
                "nome": "Kit 3 Impala",
                "cor_foco": "Rosa",
                "cores_busca": ["rosa"],
                "termo_busca": "kit 3 esmalte impala",
                "limite_resultados": 10,
            },
        ]
        mock_resolver.return_value = lambda termo, **kwargs: [
            {"titulo": "Kit 3 esmalte anita nude"},
            {"titulo": "Kit 3 esmalte impala rosa"},
        ]

        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"
        ), patch.object(agente, "ESMALTES_BUSCA_KIT_PAUSA_SEG", 0):
            out = agente.executar(enviar_alerta=True)

        self.assertTrue(out["ok"])
        self.assertEqual(out["buscas_rodada"], 2)
        self.assertEqual(out["buscas_hoje"], 2)
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("Anita", msg)
        self.assertIn("Impala", msg)
        self.assertIn("frequência", msg.lower())

    def test_montar_mensagem(self):
        msg = agente.montar_mensagem_telegram(
            "2026-07-06",
            {
                "itens": {
                    "kit3-anita": {
                        "nome": "Kit 3 Anita",
                        "marca": "anita",
                        "cor_foco": "Nude",
                        "buscas": 2,
                        "total_anuncios_acum": 20,
                        "cores_encontradas": {"nude": 5},
                    }
                }
            },
            {"total_buscas": 2, "anita": 2, "impala": 0, "itens_distintos": 1, "top_cores": []},
            [{"ok": True, "marca": "anita", "nome": "Kit 3", "cor_foco": "Nude", "termo_busca": "x", "total_anuncios": 10, "anuncios_da_marca": 8, "cores_encontradas": {"nude": 3}}],
        )
        self.assertIn("Kit 3 Anita", msg)
        self.assertIn("nude", msg.lower())


if __name__ == "__main__":
    unittest.main()
