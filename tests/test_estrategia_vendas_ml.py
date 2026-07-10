"""
tests/test_estrategia_vendas_ml.py
tests/test_agente_relatorio_estrategia_ml.py (mesmo arquivo)
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.ml import agente_relatorio_estrategia_ml as ag
from integracoes.ml import estrategia_vendas_ml as est


class EstrategiaVendasTests(unittest.TestCase):
    def test_gap_guerra_diferenciar(self):
        out = est.gerar_acoes_estrategia(
            monitor={
                "ok": True,
                "resultados": [
                    {
                        "ok": True,
                        "tipo": "termo",
                        "sku": "IMP-BAIL-005",
                        "nome": "Kit 5 Bailarina",
                        "meu_preco": 48.9,
                        "menor_preco": 30.99,
                    }
                ],
                "alertas": [],
            },
            produtos=[
                {
                    "sku": "IMP-BAIL-005",
                    "nome": "Kit Bailarina",
                    "custo": 22.0,
                    "margem_minima_pct": 15,
                    "canais": {"mercadolivre": {"preco": 48.9}},
                }
            ],
            gap_guerra_pct=25,
            max_acoes=3,
            taxa_pct=18,
        )
        tipos = [a["tipo"] for a in out["acoes"]]
        self.assertIn("diferenciar_ou_sair", tipos)
        self.assertIn("canal_proprio", tipos)
        self.assertLessEqual(len(out["acoes"]), 3)

    def test_gap_moderado_reposiciona(self):
        out = est.gerar_acoes_estrategia(
            monitor={
                "ok": True,
                "resultados": [
                    {
                        "ok": True,
                        "tipo": "termo",
                        "sku": "IMP-MIMO-003",
                        "nome": "Kit Mimo",
                        "meu_preco": 44.9,
                        "menor_preco": 40.0,
                    }
                ],
                "alertas": [],
            },
            produtos=[
                {
                    "sku": "IMP-MIMO-003",
                    "custo": 18.0,
                    "margem_minima_pct": 10,
                    "canais": {"mercadolivre": {"preco": 44.9}},
                }
            ],
            gap_alerta_pct=5,
            gap_guerra_pct=25,
            max_acoes=3,
            taxa_pct=18,
        )
        self.assertEqual(out["acoes"][0]["tipo"], "reposicionar_preco")

    def test_competitivo_ads(self):
        out = est.gerar_acoes_estrategia(
            monitor={
                "ok": True,
                "resultados": [
                    {
                        "ok": True,
                        "tipo": "termo",
                        "sku": "IMP-X",
                        "nome": "Kit X",
                        "meu_preco": 40.0,
                        "menor_preco": 40.0,
                    }
                ],
                "alertas": [],
            },
            produtos=[{"sku": "IMP-X", "custo": 15.0}],
            max_acoes=3,
        )
        self.assertEqual(out["acoes"][0]["tipo"], "investir_ads")

    def test_ameacas_loja_e_manter(self):
        out = est.gerar_acoes_estrategia(
            monitor={
                "ok": True,
                "resultados": [
                    {
                        "ok": True,
                        "tipo": "loja",
                        "id": "loja-x",
                        "nickname": "NOVAMIX",
                        "ameacas_preco": [
                            {
                                "sku": "IMP-SORT-006",
                                "nome": "Sortido",
                                "meu_preco": 49.9,
                                "menor_preco_loja": 25.0,
                            }
                        ],
                    }
                ],
                "alertas": [],
            },
            analise_loja={
                "nickname": "NOVAMIX",
                "ameacas_preco": [
                    {
                        "sku": "IMP-BAIL-005",
                        "nome": "Bailarina",
                        "meu_preco": 48.9,
                        "menor_preco_loja": 30.0,
                    }
                ],
                "estrategia": {"porte": "gigante"},
                "perfil": {"nickname": "NOVAMIX"},
            },
            produtos=[
                {"sku": "IMP-BAIL-005", "custo": 35.0, "margem_minima_pct": 15},
                {"sku": "IMP-SORT-006", "custo": 30.0, "margem_minima_pct": 15},
            ],
            gap_guerra_pct=25,
            max_acoes=3,
            taxa_pct=18,
        )
        self.assertTrue(any(a["tipo"] == "diferenciar_ou_sair" for a in out["acoes"]))

        vazio = est.gerar_acoes_estrategia(monitor={"ok": True, "resultados": []}, produtos=[])
        self.assertEqual(vazio["acoes"][0]["tipo"], "manter")

    def test_mensagem(self):
        payload = {
            "acoes": [
                {
                    "tipo": "reposicionar_preco",
                    "titulo": "Ajustar IMP-1",
                    "detalhe": "Gap 10%",
                    "prioridade": "alta",
                }
            ],
            "contexto": {"taxa_estimada_pct": 18, "monitor_itens": 1, "monitor_alertas": 0},
        }
        msg = est.montar_mensagem_estrategia(payload)
        self.assertIn("Estratégia de vendas", msg)
        self.assertIn("Ajustar IMP-1", msg)


class AgenteEstrategiaTests(unittest.TestCase):
    @patch.object(ag, "alertar_gestor", return_value=True)
    @patch.object(ag, "gestor_telegram_configurado", return_value=True)
    @patch.object(ag, "_coletar_loja")
    @patch.object(ag, "_coletar_monitor")
    def test_executar(self, mock_mon, mock_loja, _tg, _al):
        mock_mon.return_value = {
            "ok": True,
            "alertas": ["x"],
            "resultados": [
                {
                    "ok": True,
                    "tipo": "termo",
                    "sku": "IMP-BAIL-005",
                    "nome": "Bailarina",
                    "meu_preco": 48.9,
                    "menor_preco": 30.0,
                }
            ],
        }
        mock_loja.return_value = {
            "ok": True,
            "nickname": "NOVAMIX_COMERCIAL",
            "total_anuncios_coletados": 1,
            "ameacas_preco": [],
            "estrategia": {"porte": "gigante"},
            "perfil": {"nickname": "NOVAMIX_COMERCIAL"},
        }
        with patch(
            "core.catalogo_produtos.carregar_produtos_para_operacao",
            return_value=[{"sku": "IMP-BAIL-005", "custo": 20.0, "canais": {"mercadolivre": {"preco": 48.9}}}],
        ), patch.object(ag, "escrever_json_atomico"):
            out = ag.executar(enviar_alerta=True, coletar_fresco=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["alerta_enviado"])
        self.assertGreaterEqual(len(out["acoes"]), 1)
        self.assertIn("Estratégia", out["relatorio"])


if __name__ == "__main__":
    unittest.main()
