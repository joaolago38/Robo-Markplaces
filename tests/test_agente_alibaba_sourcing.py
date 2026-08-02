"""tests/test_agente_alibaba_sourcing.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from agentes.importacao import agente_alibaba_sourcing as src


class TestAlibabaSourcing(unittest.TestCase):
    @patch.object(src, "ALIBABA_SOURCING_ATIVO", False)
    def test_desligado(self):
        out = src.executar(enviar_alerta=False)
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "agente_desligado")

    @patch.object(src, "escrever_json_atomico")
    @patch("agentes.importacao.agente_alibaba_importacao_inteligente.executar")
    @patch("agentes.importacao.agente_alibaba_importacao.executar")
    def test_roda_busca_sem_alerta_e_intel_com_alerta(self, mock_busca, mock_intel, _write):
        mock_busca.return_value = {"ok": True, "alerta_enviado": False}
        mock_intel.return_value = {"ok": True, "alerta_enviado": True, "lucrativas": 2}

        out = src.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        mock_busca.assert_called_once_with(enviar_alerta=False)
        mock_intel.assert_called_once_with(enviar_alerta=True)
        self.assertTrue(out["alerta_enviado"])

    @patch.object(src, "escrever_json_atomico")
    @patch("agentes.importacao.agente_alibaba_importacao_inteligente.executar")
    @patch("agentes.importacao.agente_alibaba_importacao.executar")
    def test_ok_se_um_lado_ok(self, mock_busca, mock_intel, _write):
        mock_busca.return_value = {"ok": False, "erro": "ddg"}
        mock_intel.return_value = {"ok": True, "alerta_enviado": False}
        out = src.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
