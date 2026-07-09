"""
tests/test_agente_ml_tendencias_importacao.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.importacao import agente_ml_tendencias_importacao as agente


class AgenteMlTendenciasImportacaoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "analisar_produto_ml_vs_alibaba")
    @patch.object(agente, "_carregar_produtos")
    @patch.object(agente, "obter_cotacao_usd")
    def test_executar_envia_telegram(self, mock_cambio, mock_prod, mock_analise, mock_alertar):
        mock_cambio.return_value = {"ok": True, "usd_brl": 5.5, "fonte": "teste"}
        mock_prod.return_value = [{"id": "p1", "ativo": True, "nome": "Abraçadeira", "prioridade": 1}]
        mock_analise.return_value = {
            "ok": True,
            "id": "p1",
            "produto": "Abraçadeira",
            "total_oportunidades_alibaba": 1,
            "sinais_ml": {
                "ok": True,
                "total_anuncios": 10,
                "vendas_totais": 200,
                "score_demanda": 65,
                "preco_mediana_brl": 28.0,
                "preco_min_brl": 22.0,
            },
            "melhor_analise": {
                "lucro_razoavel": True,
                "preco_usd": 0.9,
                "moq": 5000,
                "url": "http://alibaba/x",
                "margem_melhor": {"margem_pct": 20.0, "margem_brl": 5.0, "ok": True, "custo_unitario_brl": 18.0},
            },
            "veredito": {"codigo": "importar", "label": "✅ Vale importar", "margem_pct": 20.0},
        }
        with patch.object(agente, "SNAPSHOT_PATH", self.tmp_path / "snap.json"), patch.object(
            agente, "HISTORY_PATH", self.tmp_path / "hist.json"
        ), patch.object(agente, "ML_TENDENCIAS_IMPORTACAO_PAUSA_SEG", 0):
            out = agente.executar(enviar_alerta=True)

        self.assertTrue(out["ok"])
        self.assertEqual(out["consolidado"]["vale_importar"], 1)
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("vale importar", msg.lower())
        self.assertIn("Abraçadeira", msg)

    def test_montar_mensagem(self):
        msg = agente.montar_mensagem_telegram(
            {"produtos_varridos": 1, "vale_importar": 1, "avaliar": 0, "top_importar": [{"id": "p1"}]},
            [
                {
                    "ok": True,
                    "produto": "PLA",
                    "sinais_ml": {"total_anuncios": 5, "vendas_totais": 50, "score_demanda": 50, "preco_mediana_brl": 75},
                    "veredito": {"label": "✅ Vale importar"},
                    "melhor_analise": {"preco_usd": 3.5, "moq": 100, "margem_melhor": {"margem_brl": 10, "margem_pct": 18, "ok": True}},
                    "total_oportunidades_alibaba": 2,
                }
            ],
            cotacao={"usd_brl": 5.5, "fonte": "teste"},
        )
        self.assertIn("Mercado Livre × Alibaba", msg)


if __name__ == "__main__":
    unittest.main()
