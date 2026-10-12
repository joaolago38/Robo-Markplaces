"""
tests/test_licitacao_requisitos.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.licitacao.requisitos import montar_requisitos_participacao


class LicitacaoRequisitosTests(unittest.TestCase):
    def test_pregao_comprasgov(self):
        out = montar_requisitos_participacao(
            {
                "modalidade": "Pregão - Eletrônico",
                "data_encerramento": "15/07/2026 10:00",
                "url": "https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/landing",
                "sistema_origem": "Compras.gov.br",
            }
        )
        self.assertIn("SICAF", out["checklist"][0])
        self.assertTrue(any("proposta" in c.lower() for c in out["checklist"]))
        self.assertIn("sicaf", out["url_cadastro_fornecedor"].lower())

    def test_dispensa_e_srp(self):
        out = montar_requisitos_participacao(
            {"modalidade": "Dispensa de Licitação", "srp": True, "data_encerramento": "hoje"}
        )
        self.assertTrue(any("dispensa" in c.lower() or "manifestação" in c.lower() for c in out["checklist"]))
        self.assertTrue(any("SRP" in c for c in out["checklist"]))


if __name__ == "__main__":
    unittest.main()
