"""
tests/test_agente_monitor_mercado_esmaltes.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.esmaltes import agente_monitor_mercado_esmaltes as ag


class AgenteMonitorMercadoEsmaltesTests(unittest.TestCase):
    def test_montar_painel(self):
        consolidado = {
            "total_anuncios_unicos": 40,
            "total_segmentos": 3,
            "total_oportunidades_margem": 2,
            "ranking_marcas_global": [{"marca": "Impala", "vendidos": 500, "anuncios": 20}],
            "propostas": [
                {"prioridade": "alta", "texto": "Competir com IMP-BAIL-005 em R$ 45,90"},
                {"prioridade": "media", "texto": "Cores em alta — Nude, Rosa"},
            ],
        }
        resultados = [
            {
                "ok": True,
                "prioridade": 1,
                "nome": "Kit 5",
                "total_anuncios": 20,
                "padroes_kits": [{"qtd": 5, "vendidos": 200, "preco_medio": 46.0, "anuncios": 8}],
                "tendencia_cores": [{"cor": "Nude"}],
                "destaques": [
                    {
                        "titulo": "Kit 5 Impala",
                        "preco": 44.9,
                        "quantidade_vendida": 100,
                        "descricao_kit": "5 esmalte(s) | cores: Nude",
                    }
                ],
            }
        ]
        painel = ag._montar_painel(resultados, consolidado)
        self.assertIn("Mercado esmaltes", painel)
        self.assertIn("IMP-BAIL-005", painel)
        self.assertIn("100 vend.", painel)

    def test_montar_painel_vendas_nd(self):
        consolidado = {
            "total_anuncios_unicos": 10,
            "total_segmentos": 1,
            "total_oportunidades_margem": 0,
            "ranking_marcas_global": [{"marca": "Impala", "vendidos": 0, "anuncios": 6}],
            "propostas": [
                {
                    "prioridade": "media",
                    "texto": "Kit 3: kits de 3 un mais presentes na amostra — vendas API n/d",
                }
            ],
        }
        resultados = [
            {
                "ok": True,
                "prioridade": 1,
                "nome": "Kit 3 esmaltes",
                "total_anuncios": 6,
                "padroes_kits": [{"qtd": 3, "vendidos": 0, "preco_medio": 33.48, "anuncios": 6}],
                "tendencia_cores": [{"cor": "Branco"}],
                "destaques": [
                    {
                        "titulo": "Kit 3 Esmaltes Impala",
                        "preco": 36.98,
                        "quantidade_vendida": 0,
                        "avaliacoes": 12,
                        "descricao_kit": "3 esmalte(s)",
                    }
                ],
            }
        ]
        painel = ag._montar_painel(resultados, consolidado)
        self.assertIn("vendas n/d", painel)
        self.assertNotIn("0 vend.", painel)
        self.assertIn("12 aval.", painel)

    @patch.object(ag, "alertar_gestor", return_value=True)
    @patch("integracoes.ml.ml_client.buscar_concorrentes_por_termo", return_value=[])
    @patch.object(ag, "_carregar_segmentos")
    def test_executar_vazio(self, mock_seg, _mock_busca, _mock_alertar):
        mock_seg.return_value = [
            {
                "id": "s1",
                "ativo": True,
                "nome": "Kit 5",
                "termo_busca": "kit 5 esmaltes",
                "prioridade": 1,
                "limite_resultados": 5,
            }
        ]
        with patch.object(ag, "_mapa_produtos", return_value={}):
            out = ag.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
