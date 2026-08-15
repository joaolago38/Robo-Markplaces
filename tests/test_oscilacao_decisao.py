"""tests/test_oscilacao_decisao.py"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integracoes.datadog import oscilacao_decisao as osc


class TestOscilacaoDecisao(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "decisao_oscilacao_ultima.json"
        self.patcher = patch.object(osc, "SNAPSHOT_PATH", self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_primeira_amostra_nao_e_oscilacao(self):
        out = osc.comparar(None, {"saude_score": 21.4})
        self.assertFalse(out["oscilacao"])
        self.assertTrue(out["primeira_amostra"])

    def test_saude_dentro_da_margem_nao_oscila(self):
        out = osc.comparar({"saude_score": 21.4}, {"saude_score": 22.9})
        self.assertFalse(out["oscilacao"])

    def test_saude_alem_da_margem_oscila(self):
        out = osc.comparar({"saude_score": 21.4}, {"saude_score": 42.0})
        self.assertTrue(out["oscilacao"])
        self.assertTrue(out["cuidado"])
        self.assertEqual(out["mudancas"][0]["metrica"], "saude_score")

    def test_kit_condicao_qualquer_mudanca_oscila(self):
        out = osc.comparar({"kit_condicao_ok": 2}, {"kit_condicao_ok": 1})
        self.assertTrue(out["oscilacao"])

    def test_alerta_texto_pede_cuidado(self):
        msg = osc.formatar_alerta(
            [{"metrica": "saude_score", "de": 21.4, "para": 42.0, "delta": 20.6, "limiar": 2.0}]
        )
        self.assertIn("CUIDADO", msg)
        self.assertIn("saude_score", msg)
        self.assertIn("moderado", msg.lower())

    def test_registrar_emite_e_nao_alerta_no_pytest(self):
        with patch.object(osc, "gauge") as g:
            a = osc.registrar_e_avaliar({"saude_score": 21.4})
            b = osc.registrar_e_avaliar({"saude_score": 50.0})
        self.assertFalse(a["oscilacao"])
        self.assertTrue(b["oscilacao"])
        self.assertTrue(any(c.args[0] == "decisao.oscilacao" and c.args[1] == 1.0 for c in g.call_args_list))

    def test_chave_nova_nao_e_oscilacao(self):
        out = osc.comparar({"saude_score": 21.4}, {"saude_score": 21.4, "kit_condicao_ok": 2})
        self.assertFalse(out["oscilacao"])

    def test_ausencia_nao_vira_zero(self):
        out = osc.comparar({"saude_score": 21.4}, {"kit_condicao_ok": 2})
        self.assertFalse(out["oscilacao"])

    def test_update_parcial_nao_zera_outras_metricas(self):
        with patch.object(osc, "gauge"):
            osc.registrar_e_avaliar({"saude_score": 21.4, "kit_condicao_ok": 2})
            out = osc.registrar_e_avaliar({"kit_condicao_ok": 2})
        self.assertFalse(out["oscilacao"])
        self.assertEqual(out["atual"]["saude_score"], 21.4)

    def test_snapshot_vazio_nao_oscila(self):
        with patch.object(osc, "gauge"):
            primeiro = osc.registrar_e_avaliar({"saude_score": 21.4})
            vazio = osc.registrar_e_avaliar({})
        self.assertFalse(primeiro["oscilacao"])
        self.assertFalse(vazio["oscilacao"])
        self.assertEqual(vazio["atual"]["saude_score"], 21.4)


if __name__ == "__main__":
    unittest.main()
