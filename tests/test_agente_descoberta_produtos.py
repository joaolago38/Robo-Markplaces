"""
tests/test_agente_descoberta_produtos.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.descoberta import agente_descoberta_produtos as agente
from integracoes.descoberta import alibaba_cruzamento, coletores


class TestColetores(unittest.TestCase):
    @patch("integracoes.ml.ml_client._enabled", return_value=False)
    def test_ml_nao_configurado(self, *_):
        out = coletores.coletar_mercadolivre({"termo_busca": "kit esmalte"})
        self.assertFalse(out["configurado"])

    @patch("integracoes.ml.ml_client.buscar_concorrentes_por_termo")
    @patch("integracoes.ml.ml_client._enabled", return_value=True)
    def test_ml_agrega_estatisticas(self, _en, mock_busca):
        mock_busca.return_value = [
            {"item_id": "1", "titulo": "Kit A", "preco": 40.0, "quantidade_vendida": 10, "frete_gratis": True},
            {"item_id": "2", "titulo": "Kit B", "preco": 60.0, "quantidade_vendida": 5, "frete_gratis": False},
        ]
        out = coletores.coletar_mercadolivre({"termo_busca": "kit esmalte", "limite_resultados": 5})
        self.assertTrue(out["configurado"])
        self.assertEqual(out["estatisticas"]["total_anuncios"], 2)
        self.assertEqual(out["estatisticas"]["preco_medio"], 50.0)


class TestAlibabaCruzamento(unittest.TestCase):
    @patch("integracoes.alibaba.busca.buscar_alibaba_direto")
    def test_cruzar_oportunidades(self, mock_busca):
        mock_busca.return_value = [
            {
                "titulo": "Nail kit wholesale",
                "preco_usd": 4.5,
                "moq": 200,
                "distribuidor": "Shenzhen ABC",
                "url": "https://www.alibaba.com/product-detail/1.html",
            }
        ]
        nicho = {"termo_alibaba_en": "nail polish kit", "nome": "Kits"}
        analise = {
            "oportunidades": [
                {"produto": "Kit 3 cores", "confianca": "alta", "sinal": "demanda", "termo_alibaba": "nail kit"}
            ]
        }
        out = alibaba_cruzamento.cruzar_oportunidades_com_alibaba(
            nicho, analise, max_por_oportunidade=2, pausa_seg=0
        )
        self.assertEqual(out["total_fornecedores"], 1)
        self.assertEqual(out["oportunidades"][0]["fornecedores"][0]["preco_usd"], 4.5)

    def test_estimar_margem(self):
        m = alibaba_cruzamento.estimar_margem_importacao(50.0, 5.0, cambio_usd_brl=5.0, taxa_marketplace_pct=14)
        self.assertTrue(m["ok"])
        self.assertGreater(m["margem_brl"], 0)


class TestAgenteDescoberta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "_carregar_nichos", return_value=[])
    def test_sem_nichos(self, *_):
        out = agente.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_nichos"], 0)

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "cruzar_oportunidades_com_alibaba")
    @patch.object(agente, "_analisar_com_ia")
    @patch.object(agente, "coletar")
    @patch.object(agente, "_carregar_nichos")
    def test_detecta_analise_nova_com_alibaba(self, mock_nichos, mock_coletar, mock_ia, mock_ali, mock_alertar):
        mock_nichos.return_value = [
            {
                "id": "n1",
                "ativo": True,
                "nome": "Kits esmalte",
                "marketplaces": ["mercadolivre"],
                "publico_alvo_hint": "manicures",
            }
        ]
        mock_coletar.return_value = {
            "marketplace": "mercadolivre",
            "configurado": True,
            "estatisticas": {"total_anuncios": 3, "preco_medio": 45.0, "preco_min": 35, "preco_max": 55},
        }
        mock_ia.return_value = {
            "publico_alvo": "Manicures profissionais",
            "perfil_comprador": "Compra kits presente",
            "oportunidades": [
                {
                    "produto": "Kit 3 cores",
                    "sinal": "alta demanda",
                    "confianca": "alta",
                    "acao": "testar",
                    "termo_alibaba": "nail polish kit",
                }
            ],
        }
        mock_ali.return_value = {
            "total_fornecedores": 1,
            "total_oportunidades": 1,
            "oportunidades": [
                {
                    "produto": "Kit 3 cores",
                    "fornecedores": [
                        {
                            "titulo": "Wholesale kit",
                            "preco_usd": 4.0,
                            "moq": 100,
                            "distribuidor": "Factory X",
                            "url": "https://alibaba.com/x",
                        }
                    ],
                }
            ],
        }
        hist = self.tmp_path / "hist.json"
        snap = self.tmp_path / "snap.json"
        with patch.object(agente, "HISTORY_PATH", hist), patch.object(
            agente, "SNAPSHOT_PATH", snap
        ), patch.object(agente, "DESCOBERTA_PAUSA_ENTRE_ANALISES_SEG", 0), patch.object(
            agente, "DESCOBERTA_BUSCAR_ALIBABA", True
        ):
            out1 = agente.executar(enviar_alerta=True)

        self.assertTrue(out1["ok"])
        self.assertEqual(out1["com_novos"], 1)
        self.assertEqual(out1["total_fornecedores_alibaba"], 1)
        self.assertTrue(snap.is_file())
        painel = agente._montar_painel_decisao(out1["resultados"])
        self.assertIn("Painel de decisão", painel)
        self.assertIn("Alibaba", painel)
        self.assertIn("Factory X", painel)

    def test_montar_alerta_alibaba_novos(self):
        msg = agente._montar_alerta_alibaba_novos(
            [
                {
                    "alibaba_novo": True,
                    "nicho_nome": "Kits",
                    "marketplace": "mercadolivre",
                    "cruzamento_alibaba": {
                        "total_fornecedores": 1,
                        "oportunidades": [
                            {
                                "produto": "Kit 3",
                                "termo_alibaba": "nail kit",
                                "fornecedores": [
                                    {
                                        "preco_usd": 3.5,
                                        "moq": 50,
                                        "distribuidor": "ABC Co",
                                        "url": "https://alibaba.com/1",
                                    }
                                ],
                            }
                        ],
                    },
                }
            ]
        )
        self.assertIn("Alibaba", msg)
        self.assertIn("ABC Co", msg)

    def test_fallback_sem_claude(self):
        coleta = {
            "marketplace": "mercadolivre",
            "configurado": True,
            "estatisticas": {"preco_min": 30, "preco_max": 50, "preco_medio": 40, "total_anuncios": 5},
        }
        nicho = {
            "nome": "Kits",
            "publico_alvo_hint": "manicures",
            "preco_alvo_min": 35,
            "preco_alvo_max": 55,
            "termo_alibaba_en": "nail kit wholesale",
        }
        out = agente._analise_fallback(coleta, nicho)
        self.assertIn("manicures", out["publico_alvo"])
        self.assertIn("termo_alibaba", out["oportunidades"][0])


if __name__ == "__main__":
    unittest.main()
