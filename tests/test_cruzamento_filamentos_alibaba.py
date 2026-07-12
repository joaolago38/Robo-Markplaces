"""
tests/test_cruzamento_filamentos_alibaba.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.filamentos import cruzamento_alibaba as cruz


class CruzamentoFilamentosTests(unittest.TestCase):
    def test_eh_produto_filamento(self):
        self.assertTrue(
            cruz._eh_produto_filamento({"id": "filamento-impressora-3d-pla", "nome": "PLA", "material": "PLA"})
        )
        self.assertFalse(cruz._eh_produto_filamento({"id": "abracadeira", "nome": "Abraçadeira nylon"}))

    @patch.object(cruz, "carregar_produtos_filamento_alibaba")
    def test_cruzar_com_mocks(self, mock_produtos):
        mock_produtos.return_value = [
            {
                "id": "filamento-impressora-3d-pla",
                "nome": "Filamento PLA",
                "material": "PLA",
                "termo_busca": "PLA filament wholesale",
                "termo_busca_pt": "filamento PLA",
                "termo_marketplace": "filamento pla 1kg",
                "peso_kg": 1,
                "preco_max_usd": 9,
                "moq_max": 500,
                "margem_minima_pct": 16,
                "margem_minima_reais": 8,
            }
        ]
        consolidado = {
            "preco_min": 70,
            "preco_medio": 90,
            "preco_max": 120,
            "total_filamentos_unicos": 5,
            "ranking_cores": [{"cor": "Preto", "vendidos": 100}, {"cor": "Branco", "vendidos": 50}],
            "por_termo": [
                {"material": "PLA", "preco_min": 70, "preco_medio": 90, "preco_max": 110, "total": 5}
            ],
        }

        with patch("integracoes.cambio.cotacao_usd.obter_cotacao_usd", return_value={
            "ok": True, "usd_brl": 5.5, "confiavel": True, "fonte": "api", "idade_seg": 10
        }), patch(
            "integracoes.cambio.cotacao_usd.cotacao_confiavel_para_margem", return_value=True
        ), patch(
            "integracoes.alibaba.busca.buscar_oportunidades",
            return_value=[
                {
                    "titulo": "PLA black 1kg",
                    "url": "https://www.alibaba.com/product-detail/1.html",
                    "preco_usd": 4.5,
                    "moq": 50,
                    "hash": "h1",
                }
            ],
        ), patch(
            "integracoes.importacao.analise_margem.analisar_produto_catalogo",
            return_value={
                "ok": True,
                "lucrativas": 1,
                "melhor_analise": {
                    "ok": True,
                    "preco_usd": 4.5,
                    "lucro_razoavel": True,
                    "melhor_frete": "maritimo",
                    "margem_melhor": {"ok": True, "margem_brl": 25, "margem_pct": 20},
                    "cenarios_frete": {"maritimo": {"custo_landed_brl": 45}},
                },
            },
        ):
            out = cruz.cruzar_filamentos_ml_alibaba(consolidado, [], max_cores=1, pausa_seg=0)

        self.assertTrue(out["ok"])
        self.assertEqual(out["cores_usadas"], ["Preto"])
        self.assertEqual(out["lucrativos"], 1)
        self.assertEqual(out["cruzamentos"][0]["precos_ml"]["preco_medio_brl"], 90)

    def test_formatar_secao(self):
        linhas = cruz.formatar_secao_cruzamento(
            {
                "ok": True,
                "cores_usadas": ["Preto"],
                "cambio_usd_brl": 5.5,
                "cruzamentos": [
                    {
                        "produto": "Filamento PLA",
                        "material": "PLA",
                        "precos_ml": {"preco_min_brl": 70, "preco_medio_brl": 90, "preco_max_brl": 110},
                        "total_oportunidades_alibaba": 3,
                        "lucrativa": True,
                        "melhor_analise": {
                            "ok": True,
                            "preco_usd": 4.5,
                            "cor_foco": "Preto",
                            "melhor_frete": "maritimo",
                            "margem_melhor": {"margem_brl": 20, "margem_pct": 18},
                            "cenarios_frete": {"maritimo": {"custo_landed_brl": 50}},
                        },
                        "por_cor": [{"cor": "Preto", "total_oportunidades": 2, "lucrativas": 1}],
                    }
                ],
            },
            fmt_brl=lambda v: f"R$ {v}" if v else "n/d",
        )
        texto = "\n".join(linhas)
        self.assertIn("Cruzamento Alibaba", texto)
        self.assertIn("Preto", texto)


if __name__ == "__main__":
    unittest.main()
