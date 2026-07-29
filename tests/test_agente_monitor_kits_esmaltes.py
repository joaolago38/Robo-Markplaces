"""
tests/test_agente_monitor_kits_esmaltes.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.esmaltes import agente_monitor_kits_esmaltes as agente


class AgenteMonitorKitsEsmaltesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "enriquecer_top_kits", side_effect=lambda c: c)
    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "resolver_fn_busca_esmaltes")
    @patch.object(agente, "_carregar_termos")
    def test_executar_envia_telegram_com_ranking(
        self, mock_termos, mock_resolver, mock_alertar, _enrich
    ):
        mock_termos.return_value = [
            {
                "id": "impala",
                "ativo": True,
                "nome": "Kits Impala",
                "termo_busca": "esmalte impala kit manicure",
                "limite_resultados": 10,
                "prioridade": 1,
            },
            {
                "id": "anita",
                "ativo": True,
                "nome": "Kits Anita",
                "termo_busca": "esmalte anita kit manicure",
                "limite_resultados": 10,
                "prioridade": 1,
            },
        ]
        mock_resolver.return_value.side_effect = [
            [
                {
                    "item_id": "MLB1",
                    "titulo": "Kit 10 esmaltes Impala atacado",
                    "preco": 69.0,
                    "quantidade_vendida": 300,
                },
            ],
            [
                {
                    "item_id": "MLB2",
                    "titulo": "Kit 5 esmaltes Anita nude",
                    "preco": 45.0,
                    "quantidade_vendida": 100,
                },
            ],
        ]

        with patch.object(agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"), patch.object(
            agente, "HISTORY_PATH", self.tmp_path / "hist.json"
        ), patch.object(agente, "SERIES_PATH", self.tmp_path / "series.json"), patch.object(
            agente, "GRAFICO_PATH", self.tmp_path / "g.png"
        ), patch.object(agente, "enviar_foto_gestor", return_value=True), patch.object(
            agente, "pode_alertar_esmaltes", return_value=(True, "ok")
        ), patch.object(agente, "ESMALTES_KITS_MONITOR_PAUSA_SEG", 0):
            out = agente.executar(enviar_alerta=True)

        self.assertTrue(out["ok"])
        self.assertEqual(out["total_termos"], 2)
        self.assertEqual(out["consolidado"]["total_kits_unicos"], 2)
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("radar de mercado", msg)
        self.assertIn("Marcas", msg)
        self.assertIn("Top anúncios", msg)
        self.assertIn("Legenda", msg)
        self.assertIn("n/d", msg)

    def test_montar_mensagem_nd_quando_sem_vendas(self):
        msg = agente.montar_mensagem_telegram(
            {
                "total_kits_unicos": 26,
                "total_vendas": 0,
                "kits_com_vendas_api": 0,
                "vendas_proxy_confiavel": False,
                "preco_min": 30.0,
                "preco_max": 120.0,
                "preco_medio": 55.0,
                "termos_varridos": 3,
                "ranking_marcas": [
                    {"marca": "Impala", "vendidos": 0, "anuncios": 16, "preco_medio": 56.0},
                ],
                "padroes_tamanho": [{"qtd": 10, "anuncios": 7, "vendidos": 0, "preco_medio": 61.0}],
                "top_vendas": [
                    {
                        "titulo": "Kit 10 Impala",
                        "preco": 69.0,
                        "quantidade_vendida": 0,
                        "marca": "Impala",
                        "avaliacoes": 80,
                        "nota": 4.5,
                    }
                ],
            },
            [{"ok": True, "nome": "Kits Impala", "termo_busca": "x", "total_kits": 10, "total_bruto": 12}],
        )
        self.assertIn("n/d", msg)
        self.assertNotIn("0 vendas", msg)
        self.assertIn("★4.5", msg)
        self.assertIn("radar de mercado", msg)

    def test_montar_mensagem(self):
        msg = agente.montar_mensagem_telegram(
            {
                "total_kits_unicos": 50,
                "total_vendas": 5000,
                "kits_com_vendas_api": 2,
                "vendas_proxy_confiavel": True,
                "preco_min": 30.0,
                "preco_max": 120.0,
                "preco_medio": 55.0,
                "termos_varridos": 3,
                "ranking_marcas": [
                    {"marca": "Impala", "vendidos": 3000, "anuncios": 20, "preco_medio": 58.0},
                    {"marca": "Anita", "vendidos": 1500, "anuncios": 15, "preco_medio": 42.0},
                ],
                "padroes_tamanho": [{"qtd": 10, "anuncios": 12, "vendidos": 2000, "preco_medio": 69.0}],
                "top_vendas": [
                    {
                        "titulo": "Kit 10 Impala",
                        "preco": 69.0,
                        "quantidade_vendida": 500,
                        "marca": "Impala",
                    }
                ],
            },
            [{"ok": True, "nome": "Kits Impala", "termo_busca": "x", "total_kits": 10, "total_bruto": 12}],
            deltas=["Kit X: preço caiu R$ 70.00 → R$ 60.00 (14.3%)"],
        )
        self.assertIn("Impala", msg)
        self.assertIn("500", msg)
        self.assertIn("Kit 10", msg)
        self.assertIn("Mudanças vs rodada anterior", msg)


if __name__ == "__main__":
    unittest.main()
