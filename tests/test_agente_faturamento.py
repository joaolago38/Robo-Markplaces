import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.faturamento.agente_faturamento import emitir_nfe_pedido


class TestEmitirNfeDuplicidade(unittest.TestCase):
    @patch("agentes.faturamento.agente_faturamento.criar_nfe")
    @patch("agentes.faturamento.agente_faturamento.buscar_nfe_por_pedido")
    @patch("agentes.faturamento.agente_faturamento.buscar_produto")
    def test_pedido_ja_faturado_nao_chama_criar_nfe(self, mock_buscar, mock_buscar_nfe, mock_criar):
        mock_buscar.return_value = {
            "sku": "IMP-PERL-004",
            "nome": "Kit",
            "preco": 44.9,
        }
        mock_buscar_nfe.return_value = {"id": 99, "numeroPedidoLoja": "PED-EXIST"}
        pedido = {
            "pedido_id": "PED-EXIST",
            "cliente": {"nome": "Cliente"},
            "itens": [{"sku": "IMP-PERL-004", "quantidade": 1}],
        }

        out = emitir_nfe_pedido(pedido, dry_run=False)

        self.assertTrue(out["ok"])
        self.assertTrue(out.get("ja_emitida"))
        self.assertEqual(out["nfe"]["id"], 99)
        mock_criar.assert_not_called()

    @patch("agentes.faturamento.agente_faturamento.criar_nfe", return_value={"ok": True, "data": {"id": 1}})
    @patch("agentes.faturamento.agente_faturamento.buscar_nfe_por_pedido", return_value=None)
    @patch("agentes.faturamento.agente_faturamento.buscar_produto")
    def test_pedido_novo_chama_criar_nfe(self, mock_buscar, mock_buscar_nfe, mock_criar):
        mock_buscar.return_value = {
            "sku": "IMP-PERL-004",
            "nome": "Kit",
            "preco": 44.9,
        }
        pedido = {
            "pedido_id": "PED-NOVO",
            "cliente": {"nome": "Cliente"},
            "itens": [{"sku": "IMP-PERL-004", "quantidade": 1}],
        }

        out = emitir_nfe_pedido(pedido, dry_run=False)

        self.assertTrue(out["ok"])
        self.assertNotIn("ja_emitida", out)
        mock_criar.assert_called_once()

    @patch("agentes.faturamento.agente_faturamento.alertar_critico")
    @patch("agentes.faturamento.agente_faturamento.criar_nfe", return_value={"ok": True, "data": {"id": 2}})
    @patch("agentes.faturamento.agente_faturamento.buscar_nfe_por_pedido")
    @patch("agentes.faturamento.agente_faturamento.buscar_produto")
    def test_checagem_falha_bloqueia_emissao(self, mock_buscar, mock_buscar_nfe, mock_criar, mock_alertar):
        from integracoes.bling.bling_client import NfeVerificacaoIndisponivel

        mock_buscar.return_value = {
            "sku": "IMP-PERL-004",
            "nome": "Kit",
            "preco": 44.9,
        }
        mock_buscar_nfe.side_effect = NfeVerificacaoIndisponivel("rede")
        pedido = {
            "pedido_id": "PED-FALHA",
            "cliente": {"nome": "Cliente"},
            "itens": [{"sku": "IMP-PERL-004", "quantidade": 1}],
        }

        out = emitir_nfe_pedido(pedido, dry_run=False)

        self.assertFalse(out["ok"])
        mock_criar.assert_not_called()
        mock_alertar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
