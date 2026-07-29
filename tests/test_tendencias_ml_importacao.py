"""
tests/test_tendencias_ml_importacao.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.importacao import tendencias_ml_importacao as tmi


class TendenciasMlImportacaoTests(unittest.TestCase):
    def test_score_demanda_alto(self):
        score = tmi._score_demanda(
            total_anuncios=12,
            vendas_totais=600,
            preco_min=20.0,
            preco_max=35.0,
        )
        self.assertGreaterEqual(score, 70)

    @patch("integracoes.importacao.tendencias_ml_importacao.consultar_precos_marketplace")
    @patch("integracoes.ml.ml_client.buscar_concorrentes_por_termo")
    def test_coletar_sinais_ml(self, mock_ml, mock_precos):
        mock_ml.return_value = [
            {"preco": 25.0, "quantidade_vendida": 100, "titulo": "A"},
            {"preco": 30.0, "quantidade_vendida": 200, "titulo": "B"},
            {"preco": 28.0, "quantidade_vendida": 50, "titulo": "C"},
            {"preco": 32.0, "quantidade_vendida": 80, "titulo": "D"},
        ]
        mock_precos.return_value = {
            "ok": True,
            "preco_mediana_brl": 27.5,
            "preco_min_brl": 25.0,
            "preco_max_brl": 30.0,
        }
        out = tmi.coletar_sinais_ml({"termo_marketplace": "abraçadeira nylon 200mm"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["vendas_totais"], 430)
        self.assertTrue(out["demanda_alta"])

    def test_classificar_veredito_importar(self):
        sinais = {"ok": True, "total_anuncios": 10, "demanda_alta": True, "score_demanda": 70}
        analise = {
            "total_oportunidades": 2,
            "melhor_analise": {
                "lucro_razoavel": True,
                "margem_melhor": {"margem_pct": 22.0, "margem_brl": 8.0, "ok": True},
            },
        }
        ver = tmi.classificar_veredito(sinais, analise)
        self.assertEqual(ver["codigo"], "importar")

    def test_classificar_sem_dados(self):
        ver = tmi.classificar_veredito(
            {"ok": False, "total_anuncios": 0},
            {"total_oportunidades": 0, "melhor_analise": {}},
        )
        self.assertEqual(ver["codigo"], "sem_dados")

    @patch("integracoes.importacao.tendencias_ml_importacao.analisar_produto_catalogo")
    @patch("integracoes.importacao.tendencias_ml_importacao.buscar_oportunidades_detalhado")
    @patch("integracoes.importacao.tendencias_ml_importacao.coletar_sinais_ml")
    def test_analisar_produto_pipeline(self, mock_ml, mock_ali, mock_analise):
        mock_ml.return_value = {
            "ok": True,
            "total_anuncios": 8,
            "vendas_totais": 150,
            "score_demanda": 55,
            "demanda_alta": True,
            "preco_mediana_brl": 28.0,
            "precos_marketplace": {"ok": True, "preco_mediana_brl": 28.0},
        }
        mock_ali.return_value = {
            "oportunidades": [{"preco_usd": 0.9, "moq": 5000, "titulo": "Tie", "url": "http://x"}],
            "coleta": {"bloqueado": False, "motivo": None, "direto": 1, "ddg": 0, "candidatos": 1},
        }
        mock_analise.return_value = {
            "ok": True,
            "total_oportunidades": 1,
            "lucrativas": 1,
            "melhor_analise": {
                "lucro_razoavel": True,
                "margem_melhor": {"margem_pct": 20.0, "margem_brl": 5.0, "ok": True},
            },
        }
        out = tmi.analisar_produto_ml_vs_alibaba(
            {"id": "p1", "nome": "Abraçadeira", "termo_marketplace": "abraçadeira nylon"},
            cambio_usd_brl=5.5,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["veredito"]["codigo"], "importar")

    def test_classificar_alibaba_bloqueado(self):
        ver = tmi.classificar_veredito(
            {"ok": True, "total_anuncios": 5, "demanda_alta": True},
            {"total_oportunidades": 0, "melhor_analise": {}},
            coleta_alibaba={"bloqueado": True, "motivo": "anti_bot:captcha"},
        )
        self.assertEqual(ver["codigo"], "alibaba_bloqueado")

    def test_diagnosticar_bloqueio_alibaba(self):
        diag = tmi.diagnosticar_bloqueio_alibaba(
            [
                {
                    "ok": True,
                    "coleta_alibaba": {"bloqueado": True, "motivo": "anti_bot:captcha"},
                    "veredito": {"codigo": "alibaba_bloqueado"},
                }
            ]
        )
        self.assertIsNotNone(diag)
        self.assertTrue(diag["alibaba_bloqueado"])

    def test_coleta_vazia_nao_duplica_com_bloqueio(self):
        resultados = [
            {
                "ok": True,
                "sinais_ml": {"total_anuncios": 0},
                "total_oportunidades_alibaba": 0,
                "coleta_alibaba": {"bloqueado": True, "motivo": "anti_bot:captcha"},
                "veredito": {"codigo": "alibaba_bloqueado"},
            }
        ]
        self.assertIsNone(tmi.diagnosticar_coleta_vazia(resultados))
        self.assertIsNotNone(tmi.diagnosticar_bloqueio_alibaba(resultados))


if __name__ == "__main__":
    unittest.main()
