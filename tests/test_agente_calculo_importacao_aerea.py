"""
tests/test_agente_calculo_importacao_aerea.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.importacao import agente_calculo_importacao_aerea as agente


class AgenteCalculoImportacaoAereaTests(unittest.TestCase):
    PRODUTO = {
        "id": "p-test",
        "nome": "Filamento PLA",
        "peso_kg": 1.0,
        "preco_fob_usd": 5.0,
        "moq_referencia": 10,
        "ii_pct": 16.0,
    }

    @patch("agentes.importacao.agente_calculo_importacao_aerea.obter_perfil_importador")
    def test_executar_para_oportunidade(self, mock_perfil):
        mock_perfil.return_value = {"cnpj": "52668583000127", "razao_social": "Teste"}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(agente, "LOG_DIR", Path(tmp)):
                out = agente.executar_para_oportunidade(
                    self.PRODUTO,
                    {"preco_usd": 4.0, "moq": 10, "titulo": "PLA", "url": "https://x.com"},
                    cambio_usd_brl=5.5,
                    salvar_csv=True,
                )
        self.assertTrue(out["ok"])
        self.assertIn("custo_unitario_brl", out)
        self.assertIn("csv_path", out)

    def test_executar_para_oportunidade_cambio_invalido(self):
        with patch("agentes.importacao.agente_calculo_importacao_aerea.obter_cotacao_usd") as mock_c:
            mock_c.return_value = {"usd_brl": 0}
            out = agente.executar_para_oportunidade(
                self.PRODUTO,
                {"preco_usd": 4.0, "moq": 1},
            )
        self.assertFalse(out["ok"])

    def test_executar_para_oportunidade_cambio_fallback_bloqueia(self):
        with patch(
            "agentes.importacao.agente_calculo_importacao_aerea.obter_cotacao_usd",
            return_value={"usd_brl": 5.5, "fonte": "fallback"},
        ), patch(
            "agentes.importacao.agente_calculo_importacao_aerea.cotacao_confiavel_para_margem",
            return_value=False,
        ):
            out = agente.executar_para_oportunidade(
                self.PRODUTO,
                {"preco_usd": 4.0, "moq": 1},
            )
        self.assertFalse(out["ok"])
        self.assertIn("não confiável", out.get("motivo", ""))

    @patch("agentes.importacao.agente_calculo_importacao_aerea.executar_para_oportunidade")
    @patch("agentes.importacao.agente_calculo_importacao_aerea.buscar_oportunidades")
    def test_executar_para_produto_sem_alibaba(self, mock_busca, mock_exec):
        mock_exec.return_value = {"ok": True, "custo_total_brl": 100.0}
        out = agente.executar_para_produto(self.PRODUTO, cambio_usd_brl=5.5, buscar_alibaba=False)
        mock_busca.assert_not_called()
        self.assertTrue(out["ok"])

    @patch("agentes.importacao.agente_calculo_importacao_aerea.executar_para_produto")
    @patch("agentes.importacao.agente_calculo_importacao_aerea.cotacao_confiavel_para_margem", return_value=True)
    @patch("agentes.importacao.agente_calculo_importacao_aerea.obter_cotacao_usd")
    @patch("agentes.importacao.agente_calculo_importacao_aerea._carregar_produtos")
    @patch("agentes.importacao.agente_calculo_importacao_aerea.escrever_json_atomico")
    def test_executar_catalogo(self, mock_json, mock_prod, mock_cambio, _confiavel, mock_exec):
        mock_prod.return_value = [self.PRODUTO]
        mock_cambio.return_value = {"usd_brl": 5.5, "fonte": "awesomeapi"}
        mock_exec.return_value = {"ok": True, "custo_unitario_brl": 12.0, "custo_total_brl": 120.0}
        out = agente.executar(buscar_alibaba=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["total"], 1)
        mock_json.assert_called_once()

    def test_formatar_resumo_telegram(self):
        texto = agente.formatar_resumo_telegram(
            {
                "ok": True,
                "perfil_importador": {"cnpj": "52668583000127", "razao_social": "Empresa"},
                "produto_nome": "PLA",
                "listing_titulo": "Filamento",
                "valor_aduaneiro_cif_brl": 100.0,
                "custo_total_brl": 200.0,
                "custo_unitario_brl": 20.0,
                "quantidade": 10,
                "listing_url": "https://alibaba.com/x",
            }
        )
        self.assertIn("Viracopos", texto)
        self.assertIn("R$", texto)

    def test_main_falha(self):
        with patch.object(agente, "executar", return_value={"ok": False, "motivo": "vazio"}):
            self.assertEqual(agente.main([]), 1)


if __name__ == "__main__":
    unittest.main()
