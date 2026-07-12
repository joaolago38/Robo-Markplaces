"""
tests/test_resumo_diario_novamix.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.ml import agente_resumo_diario_novamix as agente
from integracoes.ml import analise_loja_concorrente as al


class TestDesempenhoNovamix(unittest.TestCase):
    def test_ranquear_prioriza_vendas(self):
        anuncios = [
            {
                "titulo": "Kit A",
                "preco": 40,
                "quantidade_vendida": 0,
                "avaliacoes": 500,
                "permalink": "http://a",
            },
            {
                "titulo": "Kit B vendendo",
                "preco": 30.99,
                "quantidade_vendida": 120,
                "avaliacoes": 10,
                "permalink": "http://b",
            },
        ]
        top = al.ranquear_produtos_giro(anuncios, top_n=2)
        self.assertEqual(top[0]["titulo"], "Kit B vendendo")
        self.assertEqual(top[0]["fonte_giro"], "vendas_api")

    def test_proxy_avaliacoes_quando_sem_vendas(self):
        anuncios = [
            {"titulo": "Kit X", "preco": 20, "quantidade_vendida": 0, "avaliacoes": 80},
            {"titulo": "Kit Y", "preco": 25, "quantidade_vendida": 0, "avaliacoes": 200},
        ]
        top = al.ranquear_produtos_giro(anuncios, top_n=2)
        self.assertEqual(top[0]["titulo"], "Kit Y")
        self.assertEqual(top[0]["fonte_giro"], "avaliacoes_proxy")

    def test_montar_resumo_diario_inclui_secoes(self):
        analise = {
            "ok": True,
            "nickname": "NOVAMIX_COMERCIAL",
            "seller_id": "1666381510",
            "total_anuncios_coletados": 2,
            "preco_min": 30.99,
            "preco_med": 35.0,
            "preco_max": 48.0,
            "marcas": {"impala": 2},
            "ameacas_preco": [
                {
                    "sku": "IMP-BAIL-005",
                    "meu_preco": 48.9,
                    "menor_preco_loja": 30.99,
                    "gap_pct": 57.8,
                }
            ],
            "perfil": {
                "level_id": "5_green",
                "power_seller_status": "platinum",
                "transactions_total": 71494,
            },
            "estrategia": {
                "porte": "gigante",
                "ameaca_geral": "alta",
                "implicacoes_para_voce": ["Não compete só em preço"],
            },
            "anuncios": [
                {
                    "titulo": "Kit 5 Esmaltes Impala Bailarina",
                    "preco": 30.99,
                    "quantidade_vendida": 50,
                    "avaliacoes": 900,
                    "nota": 4.9,
                    "permalink": "https://produto.mercadolivre.com.br/MLB1",
                }
            ],
        }
        desempenho = al.analisar_desempenho_diario(
            analise,
            historico_anterior={"anuncios": 1, "preco_min": 35.0, "ameacas": 0},
        )
        msg = al.montar_resumo_diario(analise, desempenho, data_local="12/07/2026 08:00")
        self.assertIn("resumo diário", msg.lower())
        self.assertIn("NOVAMIX", msg)
        self.assertIn("Análise de desempenho", msg)
        self.assertIn("Produtos que estão saindo", msg)
        self.assertIn("IMP-BAIL-005", msg)
        self.assertIn("50 vendidos", msg)


class TestAgenteResumoDiario(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "analisar_loja")
    def test_executar_envia_telegram(self, mock_loja, mock_alertar):
        mock_loja.return_value = {
            "ok": True,
            "nickname": "NOVAMIX_COMERCIAL",
            "seller_id": "1666381510",
            "total_anuncios_coletados": 1,
            "preco_min": 30.99,
            "preco_med": 30.99,
            "preco_max": 30.99,
            "marcas": {"impala": 1},
            "ameacas_preco": [],
            "perfil": {"power_seller_status": "platinum", "transactions_total": 1000},
            "estrategia": {"porte": "grande", "ameaca_geral": "alta", "implicacoes_para_voce": []},
            "anuncios": [
                {
                    "titulo": "Kit Impala",
                    "preco": 30.99,
                    "quantidade_vendida": 12,
                    "avaliacoes": 40,
                    "permalink": "http://x",
                }
            ],
        }
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"
        ), patch.object(agente, "_carregar_entrada_catalogo", return_value={
            "seller_id": "1666381510",
            "nickname": "NOVAMIX_COMERCIAL",
            "termos_busca": ["kit impala"],
            "limite_resultados": 10,
        }), patch.object(agente, "NOVAMIX_RESUMO_DIARIO_ALERTA", True), patch.object(
            agente, "NOVAMIX_RESUMO_DIARIO_ENRIQUECER", False
        ):
            out = agente.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["alerta_enviado"])
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("Novamix", msg)
        self.assertIn("desempenho", msg.lower())


if __name__ == "__main__":
    unittest.main()
