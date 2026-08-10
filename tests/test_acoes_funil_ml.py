"""tests/test_acoes_funil_ml.py"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from integracoes.ml import acoes_funil_ml as af


class AcoesFunilMlTests(unittest.TestCase):
    def test_classificar_visitas_sem_venda(self):
        row = af.classificar_item_funil(
            {"item_id": "MLB1", "titulo": "PETG", "visitas_7d": 40, "unidades_pedidos": 0},
            visitas_altas=20,
        )
        self.assertEqual(row["acao"], "baixar_preco_ou_listing")
        self.assertTrue(row["critica"])

    def test_classificar_sem_visitas(self):
        row = af.classificar_item_funil(
            {"item_id": "MLB2", "visitas_7d": 0, "unidades_pedidos": 0},
        )
        self.assertEqual(row["acao"], "republicar_ou_ads")

    def test_classificar_conversao_baixa(self):
        row = af.classificar_item_funil(
            {
                "item_id": "MLB3",
                "visitas_7d": 50,
                "unidades_pedidos": 1,
                "conversao_pct": 2.0,
                "conversao_confiavel": True,
            },
            conv_baixa_pct=3.0,
            conv_boa_pct=5.0,
        )
        self.assertEqual(row["acao"], "melhorar_conversao_listing")

    def test_classificar_conversao_ok(self):
        row = af.classificar_item_funil(
            {
                "item_id": "MLB4",
                "visitas_7d": 40,
                "unidades_pedidos": 4,
                "conversao_pct": 10.0,
                "conversao_confiavel": True,
            },
            conv_boa_pct=5.0,
        )
        self.assertEqual(row["acao"], "escalar_ou_manter")

    def test_gerar_e_persistir_merge_contextos(self):
        funil = {
            "ok": True,
            "dias": 7,
            "totais": {"visitas_7d": 40, "unidades_7d": 0},
            "itens": [
                {
                    "item_id": "MLB1",
                    "titulo": "A",
                    "visitas_7d": 40,
                    "unidades_pedidos": 0,
                    "conversao_pct": 0.0,
                    "conversao_confiavel": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "acoes.json"
            a1 = af.gerar_acoes_funil(funil, contexto="filamentos_ml")
            self.assertTrue(a1["ok"])
            self.assertGreaterEqual(a1["criticas"], 1)
            af.persistir_acoes_funil(a1, caminho=path)

            funil2 = {
                "ok": True,
                "dias": 7,
                "totais": {},
                "itens": [
                    {
                        "item_id": "MLB9",
                        "titulo": "B",
                        "visitas_7d": 5,
                        "unidades_pedidos": 0,
                        "conversao_pct": 0.0,
                    }
                ],
            }
            a2 = af.gerar_acoes_funil(funil2, contexto="masterprint_petg")
            af.persistir_acoes_funil(a2, caminho=path)
            ids = af.listar_item_ids_prioridade_funil(caminho=path)
            self.assertIn("MLB1", ids)
            self.assertIn("MLB9", ids)
            data = af.carregar_acoes_funil(caminho=path)
            self.assertIn("filamentos_ml", data.get("por_contexto") or {})
            self.assertIn("masterprint_petg", data.get("por_contexto") or {})

    def test_formatar_secao(self):
        acoes = af.gerar_acoes_funil(
            {
                "ok": True,
                "itens": [
                    {
                        "item_id": "MLB1",
                        "titulo": "Filamento",
                        "visitas_7d": 30,
                        "unidades_pedidos": 0,
                    }
                ],
            }
        )
        txt = "\n".join(af.formatar_secao_acoes_funil(acoes))
        self.assertIn("AGIR — funil", txt)
        self.assertIn("MLB1", txt)

    @patch.object(af, "persistir_acoes_funil", return_value=True)
    @patch.object(af, "emitir_metricas_acoes_funil")
    def test_processar_sem_alerta(self, _em, _pers):
        out = af.processar_e_persistir_acoes(
            {"ok": True, "itens": [{"item_id": "MLB1", "visitas_7d": 0, "unidades_pedidos": 0}]},
            contexto="teste",
            prefixo_metricas="teste",
            enviar_alerta_criticas=False,
        )
        self.assertTrue(out["ok"])
        self.assertFalse(out.get("alerta_enviado"))

    @patch("core.notificador.alertar_gestor", return_value=True)
    @patch("core.notificador.gestor_telegram_configurado", return_value=True)
    @patch.object(af, "persistir_acoes_funil", return_value=True)
    @patch.object(af, "emitir_metricas_acoes_funil")
    def test_processar_alerta_criticas(self, _em, _pers, _gestor, mock_alert):
        out = af.processar_e_persistir_acoes(
            {
                "ok": True,
                "itens": [
                    {
                        "item_id": "MLB1",
                        "titulo": "PETG",
                        "visitas_7d": 40,
                        "unidades_pedidos": 0,
                        "conversao_pct": 0.0,
                        "conversao_confiavel": True,
                    }
                ],
            },
            contexto="teste_alerta",
            prefixo_metricas="teste",
            enviar_alerta_criticas=True,
        )
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out.get("criticas") or 0, 1)
        self.assertTrue(out.get("alerta_enviado"))
        mock_alert.assert_called_once()

    def test_emitir_metricas_acoes(self):
        with patch("integracoes.ml.acoes_funil_ml.gauge") as mock_g:
            af.emitir_metricas_acoes_funil(
                "pref",
                {
                    "acoes": [{"acao": "x"}],
                    "criticas": 2,
                    "por_acao": {"baixar_preco_ou_listing": 1},
                },
            )
            nomes = [c.args[0] for c in mock_g.call_args_list]
            self.assertIn("pref.funil.acoes_criticas", nomes)
            self.assertIn("pref.funil.acao.baixar_preco_ou_listing", nomes)

    def test_funil_indisponivel(self):
        out = af.gerar_acoes_funil({"ok": False, "motivo": "x"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["acoes"], [])

    def test_amostra_pequena_aguardar(self):
        row = af.classificar_item_funil(
            {
                "item_id": "MLB5",
                "visitas_7d": 5,
                "unidades_pedidos": 1,
                "conversao_pct": 20.0,
                "conversao_confiavel": False,
            },
            min_visitas_conv=10,
        )
        self.assertEqual(row["acao"], "aguardar_amostra")


if __name__ == "__main__":
    unittest.main()
