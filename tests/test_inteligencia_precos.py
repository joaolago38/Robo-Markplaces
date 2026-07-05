import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.precificacao import agente_inteligencia_precos as intel


class InteligenciaPrecosTests(unittest.TestCase):
    @patch("agentes.precificacao.agente_inteligencia_precos.alertar_gestor")
    @patch("agentes.precificacao.agente_inteligencia_precos.gestor_telegram_configurado", return_value=False)
    @patch("agentes.precificacao.agente_inteligencia_precos.coletar_sinais")
    @patch("agentes.precificacao.agente_inteligencia_precos.carregar_produtos_para_operacao")
    def test_executar_analisa_canais_ativos(self, mock_catalogo, mock_sinais, _mock_tg, _mock_alerta):
        mock_catalogo.return_value = [
            {
                "sku": "KIT-TEST",
                "nome": "Kit Teste",
                "custo": 20.0,
                "fase_atual": 1,
                "precos_por_fase": {"fase1": 45.0},
                "canais": {
                    "mercadolivre": {"ativo": True, "preco": 49.9, "item_id": "MLB1"},
                    "shopee": {"ativo": False, "preco": 0},
                },
            }
        ]
        mock_sinais.return_value = {
            "visitas_7d": 25,
            "visitas_30d": 60,
            "unidades_vendidas_7d": 0,
            "menor_preco": 44.0,
        }
        out = intel.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_analises"], 1)
        self.assertEqual(out["analises"][0]["sku"], "KIT-TEST")
        self.assertEqual(out["analises"][0]["canal"], "mercadolivre")


if __name__ == "__main__":
    unittest.main()
