"""tests/test_relatorio.py"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agentes.relatorio as relatorio


class TestRelatorio(unittest.TestCase):
    def test_montar_dados_so_estoque_sem_historico(self):
        with patch.object(relatorio, "_ler_saude_do_historico", return_value=None):
            dados = relatorio._montar_dados_relatorio([{"nome": "A"}], [])
        self.assertIn("estoque", dados)
        self.assertNotIn("saude_marketplaces", dados)

    def test_montar_dados_com_saude_historico(self):
        saude = {"resumo": {"saudavel": 2, "atencao": 1, "critico": 0}, "marketplaces": {}}
        with patch.object(relatorio, "_ler_saude_do_historico", return_value=saude):
            dados = relatorio._montar_dados_relatorio([], [])
        self.assertEqual(dados["saude_marketplaces"], saude)

    def test_ler_saude_do_historico_arquivo_valido(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hist.json"
            path.write_text(
                json.dumps({"mercadolivre": [{"score": 85, "ts": "x"}]}),
                encoding="utf-8",
            )
            with patch.object(relatorio, "HISTORY_FILE", path):
                out = relatorio._ler_saude_do_historico()
        self.assertIsNotNone(out)
        self.assertEqual(out["marketplaces"]["mercadolivre"]["status"], "saudavel")

    @patch.object(relatorio, "alertar", return_value=True)
    @patch.object(relatorio, "alertar_critico")
    @patch.object(relatorio, "sintetizar_claude", return_value="bullet 1")
    @patch.object(relatorio, "listar_produtos", return_value=[{"nome": "Kit"}])
    @patch.object(relatorio, "estoques_criticos", return_value=[])
    @patch.object(relatorio, "_ler_saude_do_historico", return_value=None)
    def test_executar_fallback_sem_dados_extras(self, *_mocks):
        self.assertTrue(relatorio.executar())
        ctx = relatorio.sintetizar_claude.call_args[0][1]
        self.assertIn("estoque", ctx)


if __name__ == "__main__":
    unittest.main()
