"""
tests/test_licitacao_busca.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.licitacao import busca as lic_busca


class LicitacaoBuscaTests(unittest.TestCase):
    def test_bate_filtro_termos(self):
        item = {"termos_busca": ["esmalte"], "excluir_termos": ["obra"]}
        self.assertTrue(lic_busca._bate_filtro_texto(item, "Aquisição de esmaltes para manicure"))
        self.assertFalse(lic_busca._bate_filtro_texto(item, "Obra civil de pavimentação"))

    def test_normalizar_pncp(self):
        raw = {
            "numeroControlePNCP": "123-1-000001/2026",
            "objetoCompra": "Kit esmaltes manicure",
            "orgaoEntidade": {"cnpj": "123", "razaoSocial": "PREFEITURA TESTE"},
            "unidadeOrgao": {"ufSigla": "SP", "municipioNome": "Campinas"},
            "modalidadeNome": "Pregão - Eletrônico",
            "dataEncerramentoProposta": "2026-07-15T10:00:00",
            "linkSistemaOrigem": "https://pncp.gov.br/app/editais/123",
            "usuarioNome": "Compras.gov.br",
        }
        det = {"valorTotalEstimado": 25000.0, "srp": False, "orcamentoSigilosoCodigo": 1}
        norm = lic_busca._normalizar_pncp(raw, detalhe=det)
        self.assertIsNotNone(norm)
        assert norm is not None
        self.assertEqual(norm["uf"], "SP")
        self.assertIn("esmalte", norm["produto"].lower())
        self.assertIn("participacao", norm)
        self.assertTrue(norm["participacao"]["checklist"])

    @patch("integracoes.licitacao.busca.buscar_detalhe_compra")
    @patch("integracoes.licitacao.busca.buscar_propostas_abertas")
    def test_buscar_licitacoes_filtra_por_termo(self, mock_prop, mock_det):
        mock_prop.return_value = {
            "data": [
                {
                    "numeroControlePNCP": "1-1-1/2026",
                    "objetoCompra": "Aquisição de esmaltes profissionais",
                    "orgaoEntidade": {"cnpj": "123", "razaoSocial": "PREFEITURA"},
                    "unidadeOrgao": {"ufSigla": "MG", "municipioNome": "BH"},
                    "modalidadeNome": "Pregão - Eletrônico",
                    "anoCompra": 2026,
                    "sequencialCompra": 1,
                    "linkSistemaOrigem": "https://pncp.gov.br/1",
                },
                {
                    "numeroControlePNCP": "2-2-2/2026",
                    "objetoCompra": "Pavimentação asfáltica",
                    "orgaoEntidade": {"cnpj": "456", "razaoSocial": "DER"},
                    "unidadeOrgao": {"ufSigla": "SP"},
                    "modalidadeNome": "Pregão - Eletrônico",
                },
            ],
            "paginasRestantes": 0,
        }
        mock_det.return_value = {"valorTotalEstimado": 12000.0, "orcamentoSigilosoCodigo": 1}
        item_cat = {
            "termos_busca": ["esmalte"],
            "excluir_termos": ["asfalto"],
            "modalidades": [6],
            "valor_min": 5000,
        }
        achados = lic_busca.buscar_licitacoes_em_fontes(item_cat, pausa_entre_fontes_seg=0)
        self.assertEqual(len(achados), 1)
        self.assertIn("esmalte", achados[0]["produto"].lower())

    @patch("integracoes.licitacao.busca.buscar_detalhe_compra", return_value={})
    @patch("integracoes.licitacao.busca.buscar_propostas_abertas")
    def test_filtra_por_uf(self, mock_prop, _mock_det):
        mock_prop.return_value = {
            "data": [
                {
                    "objetoCompra": "esmaltes",
                    "orgaoEntidade": {"cnpj": "1"},
                    "unidadeOrgao": {"ufSigla": "SP"},
                    "modalidadeNome": "Pregão",
                },
                {
                    "objetoCompra": "esmaltes",
                    "orgaoEntidade": {"cnpj": "2"},
                    "unidadeOrgao": {"ufSigla": "MG"},
                    "modalidadeNome": "Pregão",
                },
            ],
            "paginasRestantes": 0,
        }
        item_cat = {"termos_busca": ["esmalte"], "ufs": ["MG"], "modalidades": [6]}
        achados = lic_busca.buscar_licitacoes_em_fontes(item_cat, pausa_entre_fontes_seg=0)
        self.assertEqual(len(achados), 1)
        self.assertEqual(achados[0]["uf"], "MG")

    def test_valor_min_rejeita_baixo(self):
        self.assertFalse(lic_busca._valor_no_intervalo({"valor_min": 50000}, 1000.0))

    def test_todas_ufs_catalogo(self):
        from integracoes.licitacao.fontes import TODAS_UFS

        self.assertEqual(len(TODAS_UFS), 27)

    def test_formatar_valor_br(self):
        self.assertEqual(lic_busca._formatar_valor_br(1234.5), "R$ 1.234,50")


if __name__ == "__main__":
    unittest.main()
