"""
tests/test_agente_licitacoes.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.licitacao import agente_licitacoes as agente


class TestAgenteLicitacoes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "ROOT")
    def test_sem_itens_ativos(self, mock_root):
        mock_root.__truediv__ = lambda _s, rel: self.tmp_path / rel
        catalogo = self.tmp_path / "catalogo" / "licitacoes_monitoradas.json"
        catalogo.parent.mkdir(parents=True)
        catalogo.write_text("[]", encoding="utf-8")
        with patch.object(agente, "LICITACOES_CATALOGO", "catalogo/licitacoes_monitoradas.json"):
            out = agente.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_itens"], 0)

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "buscar_licitacoes_em_fontes")
    @patch.object(agente, "_carregar_itens")
    def test_alerta_novos_com_requisitos(self, mock_itens, mock_busca, mock_alertar):
        mock_itens.return_value = [
            {
                "id": "esm",
                "ativo": True,
                "nome": "Esmaltes",
                "prioridade": 1,
                "termos_busca": ["esmalte"],
            }
        ]
        mock_busca.return_value = [
            {
                "hash": "abc123",
                "produto": "Aquisição de esmaltes",
                "titulo": "Aquisição de esmaltes",
                "orgao": "PREFEITURA",
                "uf": "SP",
                "cidade": "Campinas",
                "valor_estimado": "R$ 25.000,00",
                "modalidade": "Pregão - Eletrônico",
                "data_encerramento": "15/07/2026",
                "url": "https://pncp.gov.br/app/editais/1",
                "participacao": {
                    "checklist": ["Cadastro SICAF", "Certidões negativas"],
                    "url_cadastro_fornecedor": "https://www.gov.br/compras/pt-br/fornecedor/sicaf",
                },
            }
        ]
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "LICITACOES_ALERTA_RESUMO", False
        ):
            out1 = agente.executar(enviar_alerta=True)
            out2 = agente.executar(enviar_alerta=True)

        self.assertTrue(out1["ok"])
        self.assertEqual(out1["com_novos"], 1)
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("esmalte", msg.lower())
        self.assertIn("participar", msg.lower())
        self.assertIn("SICAF", msg)
        self.assertEqual(out2["com_novos"], 0)

    def test_montar_alerta_inclui_valor_e_requisitos(self):
        msg = agente._montar_alerta_novos(
            [
                {
                    "nome": "Esmaltes",
                    "prioridade": 1,
                    "novos": [
                        {
                            "produto": "Kit esmaltes",
                            "orgao": "PREFEITURA",
                            "uf": "SP",
                            "cidade": "Campinas",
                            "valor_estimado": "R$ 10.000,00",
                            "modalidade": "Pregão - Eletrônico",
                            "data_encerramento": "20/07/2026",
                            "url": "https://pncp.gov.br/1",
                            "participacao": {
                                "checklist": ["SICAF", "Certidões"],
                                "url_cadastro_fornecedor": "https://sicaf",
                            },
                        }
                    ],
                }
            ]
        )
        self.assertIn("R$ 10.000,00", msg)
        self.assertIn("participar", msg.lower())
        self.assertIn("SICAF", msg)

    def test_resumo_varredura(self):
        msg = agente._montar_resumo_varredura(
            [{"nome": "A", "prioridade": 1, "achados_total": 3, "novos": [{}]}]
        )
        self.assertIn("27 UFs", msg)
        self.assertIn("3 achado", msg)

    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "buscar_licitacoes_em_fontes", return_value=[])
    @patch.object(agente, "_carregar_itens")
    def test_envia_resumo_sem_novos(self, mock_itens, _mock_busca, mock_alertar):
        mock_itens.return_value = [{"id": "x", "ativo": True, "nome": "Teste", "prioridade": 1}]
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "h.json"), patch.object(
            agente, "SNAPSHOT_PATH", self.tmp_path / "s.json"
        ):
            out = agente.executar(enviar_alerta=True)
        self.assertTrue(out["alerta_resumo_enviado"])
        mock_alertar.assert_called()

    @patch.object(agente, "_carregar_itens", side_effect=RuntimeError("falha simulada"))
    def test_executar_nao_lanca_excecao(self, _mock):
        out = agente.executar(enviar_alerta=False)
        self.assertFalse(out["ok"])
        self.assertIn("falha", out.get("erro", ""))


if __name__ == "__main__":
    unittest.main()
