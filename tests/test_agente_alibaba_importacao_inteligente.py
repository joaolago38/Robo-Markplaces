"""
tests/test_agente_alibaba_importacao_inteligente.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.importacao import agente_alibaba_importacao_inteligente as agente


class AgenteAlibabaInteligenteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hist = Path(self.tmp.name) / "hist.json"

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "analisar_produto_catalogo")
    @patch.object(agente, "buscar_oportunidades")
    @patch.object(agente, "_carregar_produtos")
    @patch.object(agente, "obter_cotacao_usd")
    def test_fluxo_completo(self, mock_cambio, mock_prod, mock_busca, mock_analise, _mock_alertar):
        mock_cambio.return_value = {"ok": True, "usd_brl": 5.5, "fonte": "awesomeapi", "confiavel": True}
        mock_prod.return_value = [
            {
                "id": "p1",
                "ativo": True,
                "nome": "Filamento PLA",
                "termo_busca": "pla filament",
                "peso_kg": 1,
            }
        ]
        mock_busca.return_value = [{"preco_usd": 3.5, "moq": 100, "titulo": "PLA", "url": "http://x"}]
        mock_analise.return_value = {
            "ok": True,
            "id": "p1",
            "produto": "Filamento PLA",
            "total_oportunidades": 1,
            "lucrativas": 1,
            "precos_marketplace": {"ok": True, "preco_mediana_brl": 75.0},
            "analises": [
                {
                    "ok": True,
                    "lucro_razoavel": True,
                    "titulo": "PLA",
                    "preco_usd": 3.5,
                    "melhor_frete": "maritimo",
                    "url": "http://x",
                    "margem_melhor": {"margem_brl": 20.0, "margem_pct": 25.0},
                    "cenarios_frete": {"maritimo": {"custo_unitario_brl": 35.0}},
                }
            ],
            "melhor_analise": {
                "ok": True,
                "preco_usd": 3.5,
                "moq": 100,
                "melhor_frete": "maritimo",
                "cenarios_frete": {
                    "maritimo": {"custo_unitario_brl": 35.0},
                    "aereo": {"custo_unitario_brl": 55.0},
                },
                "precos_marketplace": {"preco_mediana_brl": 75.0, "preco_min_brl": 60.0},
                "margens": {"maritimo": {"ok": True, "margem_brl": 20.0, "margem_pct": 25.0, "lucro_razoavel": True}},
            },
        }
        with patch.object(agente, "HISTORY_PATH", self.hist), patch.object(
            agente, "variacao_desde_ultima_rodada", return_value={"ok": False}
        ):
            out = agente.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_produtos"], 1)
        self.assertEqual(out["total_lucrativas"], 1)

    def test_montar_painel(self):
        msg = agente._montar_painel_produtos(
            [
                {
                    "produto": "Filamento",
                    "total_oportunidades": 2,
                    "lucrativas": 0,
                    "precos_marketplace": {"ok": True, "preco_mediana_brl": 70.0, "total_anuncios": 5},
                    "melhor_analise": None,
                    "analises": [],
                }
            ],
            {"usd_brl": 5.5, "fonte": "teste"},
        )
        self.assertIn("painel de importação", msg)
        self.assertIn("R$ 5.5", msg)

    def test_resumo_custo_formal_vcp(self):
        texto = agente._resumo_custo(
            {
                "preco_usd": 0.90,
                "moq": 5000,
                "melhor_frete": "aereo",
                "preco_normalizado": {
                    "preco_usd_listing": 0.90,
                    "preco_usd_unit": 0.009,
                    "unidade_por_preco": 100,
                    "unidade_rotulo": "100 peças",
                },
                "unidade_marketplace_qtd": 100,
                "calculo_aereo_formal": {
                    "ok": True,
                    "valor_aduaneiro_cif_brl": 500.0,
                    "ii_brl": 80.0,
                    "ipi_brl": 0.0,
                    "pis_cofins_brl": 50.0,
                    "icms_brl": 120.0,
                    "despesas_locais_brl": 200.0,
                    "custo_total_brl": 950.0,
                    "custo_unitario_brl": 0.19,
                    "quantidade": 5000,
                },
                "precos_marketplace": {
                    "ok": True,
                    "preco_mediana_brl": 28.0,
                    "preco_min_brl": 22.0,
                    "total_anuncios": 8,
                },
                "margens": {
                    "aereo": {"ok": True, "margem_brl": 5.0, "margem_pct": 18.0, "lucro_razoavel": True},
                },
            },
            cambio_usd_brl=5.5,
        )
        self.assertIn("Formal VCP", texto)
        self.assertIn("Mercado BR", texto)
        self.assertIn("pacote 100", texto)

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "analisar_produto_catalogo")
    @patch.object(agente, "buscar_oportunidades")
    @patch.object(agente, "_carregar_produtos")
    @patch.object(agente, "obter_cotacao_usd")
    def test_pula_alerta_lucro_com_cambio_fallback(
        self, mock_cambio, mock_prod, mock_busca, mock_analise, mock_alertar
    ):
        mock_cambio.return_value = {
            "ok": True,
            "usd_brl": 5.5,
            "fonte": "fallback",
            "confiavel": False,
        }
        mock_prod.return_value = [{"id": "p1", "ativo": True, "nome": "X", "termo_busca": "x"}]
        mock_busca.return_value = [{"preco_usd": 1.0, "moq": 10, "titulo": "X", "url": "http://x"}]
        mock_analise.return_value = {
            "ok": True,
            "id": "p1",
            "produto": "X",
            "total_oportunidades": 1,
            "lucrativas": 1,
            "analises": [
                {
                    "ok": True,
                    "lucro_razoavel": True,
                    "titulo": "X",
                    "preco_usd": 1.0,
                    "melhor_frete": "aereo",
                    "url": "http://x",
                    "margem_melhor": {"margem_brl": 10.0, "margem_pct": 20.0},
                    "cenarios_frete": {"aereo": {"custo_unitario_brl": 5.0}},
                }
            ],
            "melhor_analise": {"ok": True},
        }
        with patch.object(agente, "HISTORY_PATH", self.hist), patch.object(
            agente, "variacao_desde_ultima_rodada", return_value={"ok": False}
        ), patch.object(agente, "ALIBABA_INTELIGENCIA_ALERTA_RESUMO", False):
            out = agente.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertFalse(out.get("alerta_lucro"))
        # sem painel e sem lucro → nenhum alerta de margem
        for call in mock_alertar.call_args_list:
            self.assertNotIn("lucro razoável", call[0][0])


if __name__ == "__main__":
    unittest.main()
