"""
tests/test_agente_orquestrador.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.orquestrador import agente_orquestrador as orq
from agentes.orquestrador.registro_agentes import AgenteRegistrado, listar_agentes


class TestRegistroAgentes(unittest.TestCase):
    def test_lista_padrao_tem_agentes(self):
        agentes = listar_agentes()
        self.assertGreaterEqual(len(agentes), 15)
        ids = {a.id for a in agentes}
        self.assertIn("conectividade", ids)
        self.assertIn("chat_ml", ids)
        # Rotinas com workflow próprio ficam em ORQUESTRADOR_EXCLUIR (default)
        self.assertNotIn("leilao", ids)
        self.assertNotIn("alibaba", ids)
        self.assertNotIn("necessidade_manicures", ids)

    @patch("core.config.ORQUESTRADOR_EXCLUIR", set())
    def test_registro_completo_inclui_rotinas_excluidas(self):
        ids = {a.id for a in listar_agentes()}
        self.assertIn("leilao", ids)
        self.assertIn("alibaba", ids)
        self.assertIn("necessidade_manicures", ids)

    @patch("core.config.ORQUESTRADOR_EXCLUIR", {"leilao"})
    def test_excluir_por_env(self):
        ids = {a.id for a in listar_agentes()}
        self.assertNotIn("leilao", ids)


class TestOrquestrador(unittest.TestCase):
    def _agente_fake(self, aid: str, ok: bool = True, resumo: str = "ok"):
        return AgenteRegistrado(aid, aid, "test", "x:y", {})

    @patch.object(orq, "alertar_gestor", return_value=True)
    @patch.object(orq, "executar_registro")
    @patch.object(orq, "ORQUESTRADOR_PAUSA_ENTRE_AGENTES_SEG", 0)
    def test_ciclo_completo_envia_resumo(self, mock_exec, mock_alertar):
        mock_exec.side_effect = [
            {"ok": True, "com_novos": 1},
            {"ok": False, "erro": "falhou"},
        ]
        agentes = [
            self._agente_fake("a1"),
            self._agente_fake("a2"),
        ]
        out = orq.executar(enviar_resumo_telegram=True, agentes=agentes)
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["ok"], 1)
        self.assertEqual(out["falhas"], 1)
        self.assertTrue(out["resumo_telegram_enviado"])
        mock_alertar.assert_called_once()
        self.assertIn("Orquestrador 30min", mock_alertar.call_args.args[0])

    @patch.object(orq, "alertar_gestor")
    @patch.object(orq, "executar_registro", side_effect=RuntimeError("boom"))
    @patch.object(orq, "ORQUESTRADOR_PAUSA_ENTRE_AGENTES_SEG", 0)
    def test_isolamento_falha_agente(self, *_):
        out = orq.executar(
            enviar_resumo_telegram=False,
            agentes=[self._agente_fake("x")],
        )
        self.assertEqual(out["falhas"], 1)
        self.assertFalse(out["agentes"][0]["ok"])
        self.assertIn("boom", out["agentes"][0]["erro"])

    def test_interpretar_ok(self):
        self.assertTrue(orq._interpretar_ok({"ok": True}))
        self.assertFalse(orq._interpretar_ok({"ok": False}))
        self.assertTrue(orq._interpretar_ok(True))

    def test_extrair_resumo(self):
        self.assertIn("2 novos", orq._extrair_resumo({"com_novos": 2}))
        self.assertIn(
            "Impala líder",
            orq._extrair_resumo({"resumo_orquestrador": "7 produtos, Impala líder em 4/7 termos"}),
        )

    @patch.object(orq, "alertar_gestor", return_value=True)
    @patch.object(orq, "executar_registro", return_value={"ok": True})
    @patch.object(orq, "ORQUESTRADOR_PAUSA_ENTRE_AGENTES_SEG", 0)
    def test_executar_ciclo_metricas(self, *_):
        out = orq.executar_ciclo(
            agentes=[self._agente_fake("x")],
            titulo_resumo="teste",
            chave_cooldown="teste:1",
            cooldown_segundos=60,
            prefixo_metrica="teste_metrica",
            enviar_resumo_telegram=True,
            log_prefix="Teste",
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["total"], 1)


if __name__ == "__main__":
    unittest.main()
