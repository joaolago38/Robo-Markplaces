"""
tests/test_agente_relatorio_manha_ml.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.ml import agente_relatorio_manha_ml as rel


class RelatorioManhaMlTests(unittest.TestCase):
    def test_montar_relatorio_completo(self):
        ml = {
            "ok": True,
            "conta": {"perguntas_pendentes": 2, "saude": {"claims_rate": 0.02, "dias_sem_acesso": 0}},
            "ads": {"configurado": True, "campanhas_ativas": 1, "total_campanhas": 2, "gasto_total": 45.0},
            "concorrencia": [
                {
                    "titulo": "Kit 5 Impala",
                    "meu_preco": 50.0,
                    "menor_concorrente": 44.0,
                    "visitas_7d": 30,
                    "diff_preco_pct": 13.6,
                }
            ],
            "recomendacoes": ["Responder perguntas"],
        }
        precos = {
            "analises": [
                {
                    "sku": "IMP-BAIL-005",
                    "canal": "mercadolivre",
                    "preco_atual": 48.90,
                    "preco_sugerido": 45.90,
                    "delta": -3.0,
                    "acao": "reduzir para atrair vendas",
                    "prioridade": "alta",
                    "margem_minima_pct": 18,
                    "preco_concorrente": 44.0,
                    "lucro_operacao": {
                        "lucro_ok": True,
                        "margem_sugerida_pct": 22.5,
                        "sugerido_reais": 10.5,
                    },
                }
            ]
        }
        conc = {"resultados": [{"nome": "Kit 5", "menor_preco": 44.0, "meu_preco": 48.90}], "alertas": []}
        anita = {"resultados": []}
        msg = rel._montar_relatorio(ml, precos, conc, anita)
        self.assertIn("Relatório manhã", msg)
        self.assertIn("Propostas de preço", msg)
        self.assertIn("IMP-BAIL-005", msg)
        self.assertIn("45,90", msg)

    @patch.object(rel, "alertar_gestor", return_value=True)
    @patch("agentes.esmaltes.agente_monitor_anita.executar")
    @patch("agentes.ml.agente_monitor_concorrentes.executar")
    @patch("agentes.precificacao.agente_inteligencia_precos.executar")
    @patch("agentes.ml.agente_monitor_ml.analisar")
    def test_executar_consolidado(self, mock_ml, mock_precos, mock_conc, mock_anita, _mock_alertar):
        mock_ml.return_value = {"ok": True, "conta": {}, "ads": {}, "concorrencia": [], "recomendacoes": []}
        mock_precos.return_value = {"ok": True, "analises": []}
        mock_conc.return_value = {"ok": True, "resultados": [], "alertas": []}
        mock_anita.return_value = {"ok": True, "resultados": []}
        out = rel.executar(enviar_alerta=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["alerta_enviado"])


if __name__ == "__main__":
    unittest.main()
