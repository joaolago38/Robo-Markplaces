"""
tests/test_agente_leilao_veiculo.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.leilao import agente_leilao_veiculo as agente


class TestAgenteLeilaoVeiculo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "ROOT")
    def test_sem_veiculos_ativos(self, mock_root):
        mock_root.__truediv__ = lambda _s, rel: self.tmp_path / rel
        catalogo = self.tmp_path / "catalogo" / "leiloes_veiculos_monitorados.json"
        catalogo.parent.mkdir(parents=True)
        catalogo.write_text("[]", encoding="utf-8")
        with patch.object(agente, "LEILAO_VEICULOS_CATALOGO", "catalogo/leiloes_veiculos_monitorados.json"):
            out = agente.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_veiculos"], 0)

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "buscar_veiculo_em_fontes")
    @patch.object(agente, "_carregar_veiculos")
    def test_alerta_apenas_novos(self, mock_veiculos, mock_busca, mock_alertar):
        mock_veiculos.return_value = [
            {"id": "v1", "ativo": True, "marca": "Fiat", "modelo": "Uno", "ano_min": 2010, "ano_max": 2015}
        ]
        mock_busca.return_value = [
            {
                "hash": "abc123",
                "url": "https://copart.com.br/1",
                "titulo": "Fiat Uno 2012 leilão Campinas/SP",
                "snippet": "lance R$ 9.800,00",
                "fonte_nome": "Copart",
                "fonte_id": "copart",
                "fonte_tipo": "leiloeiro",
                "marca": "Fiat",
                "modelo": "Uno",
                "ano": 2012,
                "valor": "R$ 9.800,00",
                "cidade": "Campinas",
                "uf": "SP",
            }
        ]
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"):
            out1 = agente.executar(enviar_alerta=True)
            out2 = agente.executar(enviar_alerta=True)

        self.assertTrue(out1["ok"])
        self.assertEqual(out1["com_novos"], 1)
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("Campinas/SP", msg)
        self.assertIn("Fiat Uno 2012", msg)
        self.assertIn("R$ 9.800,00", msg)
        self.assertEqual(out2["com_novos"], 0)

    def test_montar_alerta_detran(self):
        msg = agente._montar_alerta(
            [
                {
                    "veiculo": "Honda Civic",
                    "prioridade": 1,
                    "novos": [
                        {
                            "fonte_tipo": "detran",
                            "fonte_nome": "DETRAN Paraná",
                            "uf": "PR",
                            "cidade": "Curitiba",
                            "marca": "Honda",
                            "modelo": "Civic",
                            "ano": 2016,
                            "valor": "R$ 25.000,00",
                            "data_leilao": "20/08/2026",
                            "url_cadastro": "https://www.detran.pr.gov.br/leilao-de-veiculos",
                            "titulo": "Civic leilão",
                            "url": "https://detran.pr.gov.br/x",
                            "url_anuncio": "https://detran.pr.gov.br/x",
                        }
                    ],
                }
            ]
        )
        self.assertIn("Curitiba — DETRAN Paraná", msg)
        self.assertIn("Honda Civic 2016", msg)
        self.assertIn("R$ 25.000,00", msg)
        self.assertIn("20/08/2026", msg)
        self.assertIn("Cadastro: https://www.detran.pr.gov.br/leilao-de-veiculos", msg)

    @patch.object(agente, "_carregar_veiculos", side_effect=RuntimeError("boom"))
    def test_nunca_lanca_excecao(self, *_):
        out = agente.executar(enviar_alerta=False)
        self.assertFalse(out["ok"])
        self.assertIn("boom", out["erro"])


if __name__ == "__main__":
    unittest.main()
