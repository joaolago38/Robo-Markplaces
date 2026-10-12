"""
tests/test_avaliacao_ia_leilao_alibaba.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.importacao import avaliacao_ia_parametros as ia_alibaba
from integracoes.leilao import avaliacao_ia_parametros as ia_leilao


class TestAvaliacaoIaLeilao(unittest.TestCase):
    @patch("integracoes.leilao.avaliacao_ia_parametros.perguntar_estruturado")
    def test_avaliar_leilao_veiculos_chama_claude(self, mock_claude):
        mock_claude.return_value = {
            "resumo_situacao": "Poucos achados vantajosos.",
            "ajustes_parametros": [
                {
                    "parametro": "LEILAO_MARGEM_FIPE_MIN_PCT",
                    "valor_atual": "25",
                    "valor_sugerido": "22",
                    "motivo": "Aumentar captura",
                    "confianca": "media",
                }
            ],
        }
        out = ia_leilao.avaliar_parametros_leilao_veiculos(
            veiculos_catalogo=[{"id": "gol", "marca": "VW", "modelo": "Gol", "ativo": True}],
            resultados=[{"id": "gol", "achados_total": 2, "vantajosos_total": 0, "novos": []}],
        )
        self.assertIsNotNone(out)
        mock_claude.assert_called_once()
        texto = ia_leilao.formatar_secao_ia(out)
        self.assertIn("LEILAO_MARGEM_FIPE_MIN_PCT", texto)

    def test_formatar_secao_ia_vazio(self):
        self.assertEqual(ia_leilao.formatar_secao_ia(None), "")


class TestAvaliacaoIaAlibaba(unittest.TestCase):
    @patch("integracoes.importacao.avaliacao_ia_parametros.perguntar_estruturado")
    def test_avaliar_alibaba_inteligencia(self, mock_claude):
        mock_claude.return_value = {
            "resumo_situacao": "Câmbio estável, margens apertadas.",
            "produtos": [
                {
                    "produto_id": "pla",
                    "parametros_sugeridos": {"preco_max_usd": 4.0, "moq_max": 150},
                    "motivo": "Ampliar busca",
                    "confianca": "alta",
                }
            ],
        }
        out = ia_alibaba.avaliar_parametros_alibaba_inteligencia(
            produtos_catalogo=[{"id": "pla", "nome": "PLA", "preco_max_usd": 4.5}],
            resultados=[{"id": "pla", "lucrativas": 0, "total_oportunidades": 3}],
            cotacao={"usd_brl": 5.5},
        )
        self.assertIsNotNone(out)
        texto = ia_alibaba.formatar_secao_ia(out)
        self.assertIn("preco_max_usd", texto)


class TestAgentesIntegracaoIa(unittest.TestCase):
    @patch("agentes.leilao.agente_leilao_veiculo.avaliar_parametros_leilao_veiculos")
    @patch("agentes.leilao.agente_leilao_veiculo._carregar_veiculos")
    @patch("agentes.leilao.agente_leilao_veiculo._monitorar_veiculo")
    @patch("agentes.leilao.agente_leilao_veiculo._carregar_historico", return_value={})
    @patch("agentes.leilao.agente_leilao_veiculo._salvar_historico")
    @patch("agentes.leilao.agente_leilao_veiculo.escrever_json_atomico")
    @patch("agentes.leilao.agente_leilao_veiculo.LEILAO_IA_AVALIAR_PARAMETROS", True)
    @patch("agentes.leilao.agente_leilao_veiculo.LEILAO_ALERTA_RESUMO", False)
    def test_leilao_executar_inclui_ia(self, *_mocks):
        from agentes.leilao import agente_leilao_veiculo as ag

        ag._carregar_veiculos.return_value = [{"id": "gol", "ativo": True, "prioridade": 1}]
        ag._monitorar_veiculo.return_value = {
            "id": "gol",
            "achados_total": 1,
            "vantajosos_total": 0,
            "novos": [],
            "novos_vantajosos": [],
            "ok": True,
        }
        ag.avaliar_parametros_leilao_veiculos.return_value = {"resumo_situacao": "ok", "ajustes_parametros": []}
        out = ag.executar(enviar_alerta=False)
        self.assertTrue(out.get("ok"))
        self.assertIn("avaliacao_ia_parametros", out)


if __name__ == "__main__":
    unittest.main()
