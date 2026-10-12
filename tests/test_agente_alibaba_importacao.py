"""
tests/test_agente_alibaba_importacao.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.importacao import agente_alibaba_importacao as agente


class TestAgenteAlibabaImportacao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch.object(agente, "_carregar_produtos", return_value=[])
    def test_sem_produtos_ativos(self, *_):
        out = agente.executar(enviar_alerta=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total_produtos"], 0)

    @patch.object(agente, "obter_cotacao_usd", return_value={"ok": True, "usd_brl": 5.5, "fonte": "awesomeapi", "confiavel": True})
    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "buscar_oportunidades")
    @patch.object(agente, "_carregar_produtos")
    def test_loga_valores_encontrados(self, mock_produtos, mock_busca, _mock_alertar, _cotacao):
        mock_produtos.return_value = [
            {
                "id": "p1",
                "ativo": True,
                "nome": "Filamento 3D",
                "termo_busca": "3D printer filament",
                "preco_max_usd": 4.5,
                "moq_max": 200,
            }
        ]
        mock_busca.return_value = [
            {
                "hash": "abc",
                "url": "https://www.alibaba.com/product-detail/1.html",
                "titulo": "PLA filament 1kg",
                "preco_usd": 3.2,
                "moq": 50,
                "distribuidor": "Shenzhen ABC Technology Co., Ltd.",
            }
        ]
        hist = self.tmp_path / "hist.json"
        with patch.object(agente, "HISTORY_PATH", hist):
            with self.assertLogs("agente_alibaba_importacao", level="INFO") as logs:
                agente.executar(enviar_alerta=False)
        joined = "\n".join(logs.output)
        self.assertIn("US$ 3.20", joined)
        self.assertIn("MOQ 50", joined)
        self.assertIn("Shenzhen ABC Technology Co., Ltd.", joined)

    @patch.object(agente, "obter_cotacao_usd", return_value={"ok": True, "usd_brl": 5.5, "fonte": "awesomeapi", "confiavel": True})
    @patch.object(agente, "buscar_oportunidades", return_value=[])
    @patch.object(agente, "_carregar_produtos")
    def test_loga_ddg_quando_sem_oportunidades(self, mock_produtos, _mock_busca, _cotacao):
        mock_produtos.return_value = [
            {
                "id": "p1",
                "ativo": True,
                "nome": "Filamento 3D",
                "termo_busca": "filament",
            }
        ]
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "mensagem_circuit_breaker", return_value="DDG circuit breaker ativo — liberação em ~60s"
        ):
            with self.assertLogs("agente_alibaba_importacao", level="WARNING") as logs:
                agente.executar(enviar_alerta=False)
        self.assertTrue(any("circuit breaker" in line for line in logs.output))

    @patch.object(agente, "obter_cotacao_usd", return_value={"ok": True, "usd_brl": 5.5, "fonte": "awesomeapi", "confiavel": True})
    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "buscar_oportunidades")
    @patch.object(agente, "_carregar_produtos")
    def test_alerta_somente_novos(self, mock_produtos, mock_busca, mock_alertar, _cotacao):
        mock_produtos.return_value = [
            {
                "id": "p1",
                "ativo": True,
                "nome": "Frasco",
                "termo_busca": "nail polish bottle",
                "preco_max_usd": 0.5,
            }
        ]
        mock_busca.return_value = [
            {
                "hash": "abc",
                "url": "https://www.alibaba.com/product-detail/1.html",
                "titulo": "Bottle wholesale",
                "preco_usd": 0.2,
                "moq": 100,
            }
        ]
        hist = self.tmp_path / "hist.json"
        with patch.object(agente, "HISTORY_PATH", hist), patch.object(
            agente, "ALIBABA_ALERTA_RESUMO", False
        ):
            out1 = agente.executar(enviar_alerta=True)
            out2 = agente.executar(enviar_alerta=True)

        self.assertTrue(out1["ok"])
        self.assertEqual(out1["com_novos"], 1)
        mock_alertar.assert_called_once()
        msg = mock_alertar.call_args[0][0]
        self.assertIn("US$ 0.20", msg)
        self.assertIn("R$", msg)
        self.assertEqual(out2["com_novos"], 0)

    def test_montar_alerta_mostra_brl(self):
        msg = agente._montar_alerta(
            [
                {
                    "produto": "Frasco",
                    "novos": [
                        {
                            "titulo": "Bottle",
                            "preco_usd": 0.2,
                            "moq": 100,
                            "url": "http://x",
                            "distribuidor": "Factory X",
                        }
                    ],
                }
            ],
            cotacao={"ok": True, "usd_brl": 5.0, "fonte": "awesomeapi", "confiavel": True},
        )
        self.assertIn("US$ 0.20", msg)
        self.assertIn("R$ 1,00", msg)
        self.assertIn("Dólar", msg)

    def test_montar_resumo_varredura(self):
        msg = agente._montar_resumo_varredura(
            [
                {
                    "produto": "Filamento 3D",
                    "oportunidades_total": 3,
                    "novos": [{"hash": "a"}],
                }
            ]
        )
        self.assertIn("resumo da varredura", msg)
        self.assertIn("Filamento 3D", msg)
        self.assertIn("3 oportunidade(s)", msg)

    @patch.object(agente, "obter_cotacao_usd", return_value={"ok": True, "usd_brl": 5.5, "fonte": "awesomeapi", "confiavel": True})
    @patch.object(agente, "alertar_gestor", return_value=True)
    @patch.object(agente, "buscar_oportunidades", return_value=[])
    @patch.object(agente, "_carregar_produtos")
    def test_envia_resumo_mesmo_sem_novos(self, mock_produtos, _mock_busca, mock_alertar, _cotacao):
        mock_produtos.return_value = [
            {"id": "p1", "ativo": True, "nome": "Filamento 3D", "termo_busca": "filament"}
        ]
        with patch.object(agente, "HISTORY_PATH", self.tmp_path / "hist.json"), patch.object(
            agente, "ALIBABA_ALERTA_RESUMO", True
        ):
            out = agente.executar(enviar_alerta=True)
        self.assertTrue(out["alerta_resumo_enviado"])
        self.assertIn("resumo da varredura", mock_alertar.call_args[0][0])

    @patch.object(agente, "_carregar_produtos", side_effect=RuntimeError("boom"))
    def test_nunca_lanca_excecao(self, *_):
        out = agente.executar(enviar_alerta=False)
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
