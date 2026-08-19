"""tests/test_alerta_pendencias_loja.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.ml.alerta_pendencias_loja import (
    classificar_pendencias_p0,
    emitir_alerta_p0,
    emitir_alerta_p0_do_resumo,
    montar_mensagem_p0,
)


class TestClassificarP0(unittest.TestCase):
    def test_loja_limpa(self):
        out = classificar_pendencias_p0()
        self.assertFalse(out["tem_p0"])
        self.assertEqual(out["itens"], [])

    def test_envio_e_pergunta(self):
        out = classificar_pendencias_p0(perguntas_pendentes=2, envios_pendentes=1)
        self.assertTrue(out["tem_p0"])
        self.assertEqual(out["assinatura"], "e1:q2:f0:c0:corok")
        msg = montar_mensagem_p0(out)
        self.assertIn("Envio pendente", msg)
        self.assertIn("Pergunta em aberto", msg)

    def test_cor_laranja(self):
        out = classificar_pendencias_p0(level_id="2_orange")
        self.assertTrue(out["tem_p0"])
        self.assertIn("2_orange", out["assinatura"])


class TestEmitirP0(unittest.TestCase):
    @patch("integracoes.ml.alerta_pendencias_loja.incrementar")
    @patch("integracoes.ml.alerta_pendencias_loja.alertar_gestor", return_value=True)
    def test_nao_envia_sem_p0(self, mock_tg, _inc):
        self.assertFalse(emitir_alerta_p0(classificar_pendencias_p0()))
        mock_tg.assert_not_called()

    @patch("integracoes.ml.alerta_pendencias_loja.ML_LOJA_P0_COOLDOWN_SEG", 1800)
    @patch("integracoes.ml.alerta_pendencias_loja.incrementar")
    @patch("integracoes.ml.alerta_pendencias_loja.alertar_gestor", return_value=True)
    def test_envia_com_chave_de_estado(self, mock_tg, _inc):
        pend = classificar_pendencias_p0(envios_pendentes=1)
        self.assertTrue(emitir_alerta_p0(pend))
        kwargs = mock_tg.call_args.kwargs
        self.assertEqual(kwargs["chave"], "ml:loja:p0:e1:q0:f0:c0:corok")
        self.assertEqual(kwargs["cooldown_segundos"], 1800)

    @patch("integracoes.ml.alerta_pendencias_loja.emitir_alerta_p0", return_value=True)
    def test_resumo_com_envio(self, mock_emit):
        ok = emitir_alerta_p0_do_resumo(
            {
                "ok": True,
                "perguntas_pendentes": 0,
                "envios_pendentes": 3,
                "pos_venda_ok": True,
                "pos_venda_claims": 0,
                "reputacao": {"cor": "Verde", "atraso_rate": 0, "cancelamentos_rate": 0, "claims_rate": 0},
            }
        )
        self.assertTrue(ok)
        pend = mock_emit.call_args.args[0]
        self.assertEqual(pend["envios_pendentes"], 3)

    def test_taxas_congelam(self):
        out = classificar_pendencias_p0(atraso_rate=0.06, cancelamentos_rate=0.05, claims_rate=0.07)
        self.assertTrue(out["tem_p0"])
        self.assertEqual(len(out["itens"]), 3)

    @patch("integracoes.ml.ml_client.contar_claims_abertos", return_value={"ok": True, "total": 0})
    @patch("integracoes.ml.ml_client.contar_envios_pendentes", return_value={"ok": True, "total": 2})
    @patch("integracoes.ml.alerta_pendencias_loja.emitir_alerta_p0", return_value=True)
    def test_ciclo_usa_envios_da_api(self, mock_emit, _env, _cl):
        from integracoes.ml.alerta_pendencias_loja import emitir_alerta_p0_do_ciclo

        out = emitir_alerta_p0_do_ciclo(
            chat_falhas=1,
            perguntas_pendentes=0,
            reputacao={"level_id": "5_green"},
        )
        self.assertTrue(out["tem_p0"])
        self.assertEqual(out["envios_pendentes"], 2)
        self.assertEqual(out["chat_falhas"], 1)
        self.assertTrue(out["enviado"])


if __name__ == "__main__":
    unittest.main()
