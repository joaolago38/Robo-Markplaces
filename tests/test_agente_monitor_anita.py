"""
tests/test_agente_monitor_anita.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.esmaltes import agente_monitor_anita as agente


class AgenteMonitorAnitaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hist = Path(self.tmp.name) / "hist.json"

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "ml_client")
    @patch.object(agente, "_carregar_produtos")
    def test_fluxo_completo(self, mock_prod, mock_ml, _mock_alertar):
        mock_prod.return_value = [
            {
                "id": "p1",
                "ativo": True,
                "prioridade": 1,
                "nome": "Kit 5 Anita",
                "tipo": "kit",
                "termo_busca": "kit 5 anita",
                "qtd_esmaltes_preferencia": 5,
                "cores_preferencia": ["Nude"],
                "meu_preco": 48.90,
                "custo_total": 24.0,
                "taxa_marketplace_pct": 18,
                "limite_resultados": 10,
            }
        ]
        mock_ml.buscar_concorrentes_por_termo.return_value = [
            {"titulo": "Kit 5 Esmaltes Anita Nude", "preco": 45.0, "quantidade_vendida": 120},
            {"titulo": "Kit 5 Impala Bailarina", "preco": 42.0, "quantidade_vendida": 200},
        ]
        with patch.object(agente, "HISTORY_PATH", self.hist), patch.object(
            agente, "ANITA_PAUSA_ENTRE_BUSCAS_SEG", 0
        ):
            out = agente.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_produtos"], 1)
        self.assertTrue(out["alerta_enviado"])
        self.assertIn("resumo_orquestrador", out)
        self.assertIn("Impala", out["resumo_orquestrador"])

    def test_consolidar_impala(self):
        c = agente.consolidar_impala(
            [
                {
                    "ok": True,
                    "impala_lider_vendas": True,
                    "total_impala": 2,
                    "unidades_vendidas_impala": 200,
                    "unidades_vendidas_anita": 100,
                    "menor_preco_impala": 39.9,
                    "margem_minha": {"margem_operacional_pct": 30.0},
                },
                {
                    "ok": True,
                    "impala_lider_vendas": False,
                    "total_impala": 1,
                    "unidades_vendidas_impala": 50,
                    "unidades_vendidas_anita": 80,
                    "share_impala_pct": 38.5,
                    "margem_minha": {"margem_operacional_pct": 28.0},
                },
            ]
        )
        self.assertEqual(c["termos_impala_lider"], 1)
        self.assertEqual(c["unidades_vendidas_impala"], 250)
        self.assertAlmostEqual(c["share_impala_global_pct"], 250 / 430 * 100, places=1)

    def test_montar_painel(self):
        consolidado = {
            "termos_impala_lider": 2,
            "termos_monitorados": 3,
            "unidades_vendidas_impala": 320,
            "unidades_vendidas_anita": 180,
            "share_impala_global_pct": 64.0,
            "menor_preco_impala": 38.5,
            "margem_media_pct": 31.2,
        }
        msg = agente._montar_painel(
            [
                {
                    "nome": "Kit 5 Anita",
                    "prioridade": 1,
                    "tipo": "kit",
                    "meu_preco": 48.90,
                    "total_anuncios": 5,
                    "total_anita": 2,
                    "marca_mais_vendida": "Impala",
                    "menor_preco_anita": 44.0,
                    "total_impala": 3,
                    "unidades_vendidas_impala": 200,
                    "unidades_vendidas_anita": 120,
                    "share_impala_pct": 62.5,
                    "menor_preco_impala": 38.5,
                    "preco_medio_impala": 41.0,
                    "margem_minha": {"margem_operacional_pct": 32.5, "lucro_reais": 15.9},
                    "divergencias_kit": 1,
                    "divergencias_cor": 0,
                    "ranking_marcas": [
                        {"marca": "Impala", "vendidos": 200, "anuncios": 3},
                        {"marca": "Anita", "vendidos": 120, "anuncios": 2},
                    ],
                    "analises": [],
                }
            ],
            consolidado,
        )
        self.assertIn("Desempenho Impala", msg)
        self.assertIn("Seus kits Impala", msg)
        self.assertIn("Anita", msg)
        self.assertIn("margem", msg)
        self.assertIn("Impala", msg)

    def test_montar_painel_aviso_coleta_vazia(self):
        diag = {
            "coleta_vazia": True,
            "produtos": 4,
            "dicas": ["Brave Search retornou 0"],
        }
        msg = agente._montar_painel(
            [
                {
                    "nome": "Kit 5 Impala",
                    "prioridade": 1,
                    "meu_preco": 48.90,
                    "total_anuncios": 0,
                    "total_anita": 0,
                    "total_impala": 0,
                    "marca_mais_vendida": "n/d",
                    "margem_minha": {"margem_operacional_pct": 32.0, "lucro_reais": 10.0},
                    "analises": [],
                }
            ],
            {"termos_monitorados": 1, "termos_impala_lider": 0},
            diag_coleta=diag,
        )
        self.assertIn("Busca ML sem resultados", msg)
        self.assertIn("Kit 5 Impala", msg)

    def test_diagnosticar_coleta_vazia(self):
        vazio = [{"ok": True, "total_anuncios": 0}]
        self.assertIsNotNone(agente.diagnosticar_coleta_vazia(vazio))
        com_dados = [{"ok": True, "total_anuncios": 3}]
        self.assertIsNone(agente.diagnosticar_coleta_vazia(com_dados))


if __name__ == "__main__":
    unittest.main()
