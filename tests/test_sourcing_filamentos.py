"""tests/test_sourcing_filamentos.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.filamentos import sourcing_filamentos as src


class TestCustoBr(unittest.TestCase):
    def test_custo_direto(self):
        self.assertEqual(src.custo_br_unitario({"custo_unitario_brl": 45.96}), 45.96)

    def test_custo_via_ipi(self):
        self.assertAlmostEqual(
            src.custo_br_unitario({"preco_base_brl": 43.15, "ipi_pct": 6.5}),
            45.95,
            places=2,
        )


class TestVereditos(unittest.TestCase):
    def test_petg_br_barato_vs_china_cara(self):
        out = src.analisar_material(
            "PETG",
            fornecedor_br={
                "id": "br-petg",
                "fornecedor": "Dist BR",
                "custo_unitario_brl": 45.96,
                "peso_kg": 1.0,
            },
            precos_ml={"preco_min": 89.0, "preco_medio": 99.9, "preco_max": 120.0},
            cambio_usd_brl=5.55,
            fob_usd=4.5,
            moq_china=20,
        )
        self.assertEqual(out["veredito"], "COMPRAR_BR")
        self.assertGreater(out["china"]["custo_unitario_maritimo_brl"], 45.96)

    def test_importar_china_quando_br_caro_e_lote_bom(self):
        # BR caro; China com FOB baixo e lote grande dilui despachante
        with patch.object(src, "FILAMENTOS_SOURCING_MARGEM_MIN_PCT", 5.0):
            with patch.object(src, "FILAMENTOS_SOURCING_TAXA_ML_PCT", 16.0):
                out = src.analisar_material(
                    "PLA",
                    fornecedor_br={
                        "id": "br-pla",
                        "custo_unitario_brl": 95.0,
                        "peso_kg": 1.0,
                    },
                    precos_ml={"preco_min": 110.0, "preco_medio": 130.0, "preco_max": 150.0},
                    cambio_usd_brl=5.55,
                    fob_usd=3.5,
                    moq_china=100,
                    preco_venda_brl=130.0,
                )
        self.assertEqual(out["veredito"], "IMPORTAR_CHINA")
        self.assertLess(out["china"]["custo_unitario_maritimo_brl"], 95.0)

    def test_nao_compensa_quando_venda_baixa(self):
        out = src.analisar_material(
            "PETG",
            fornecedor_br={"custo_unitario_brl": 45.96, "peso_kg": 1.0},
            precos_ml={"preco_min": 40.0, "preco_medio": 42.0, "preco_max": 45.0},
            cambio_usd_brl=5.55,
            fob_usd=4.5,
            moq_china=20,
            preco_venda_brl=42.0,
        )
        self.assertEqual(out["veredito"], "NAO_COMPENSA")


class TestAnalisarSourcing(unittest.TestCase):
    def test_analisar_com_fornecedor_petg(self):
        resultados = [
            {
                "ok": True,
                "material": "PETG",
                "preco_min": 85.0,
                "preco_medio": 99.0,
                "preco_max": 130.0,
            }
        ]
        forn = [
            {
                "id": "br-petg",
                "ativo": True,
                "material": "PETG",
                "fornecedor": "Dist",
                "custo_unitario_brl": 45.96,
                "peso_kg": 1.0,
                "prioridade": 1,
            }
        ]
        out = src.analisar_sourcing(
            {"preco_medio": 99.0},
            resultados,
            cruzamento=None,
            cambio_usd_brl=5.55,
            fornecedores_br=forn,
        )
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["resumo_vereditos"]["COMPRAR_BR"], 1)
        petg = next(a for a in out["analises"] if a["material"] == "PETG")
        self.assertEqual(petg["veredito"], "COMPRAR_BR")

    def test_formatar_secao(self):
        sourcing = {
            "ok": True,
            "ncm": "3916.90.10",
            "moq_china_padrao": 20,
            "cambio_usd_brl": 5.55,
            "resumo_vereditos": {"COMPRAR_BR": 1, "IMPORTAR_CHINA": 0, "NAO_COMPENSA": 0},
            "analises": [
                {
                    "material": "PETG",
                    "veredito": "COMPRAR_BR",
                    "preco_venda_brl": 99.9,
                    "fornecedor_br": {"custo_unitario_brl": 45.96},
                    "china": {"custo_unitario_maritimo_brl": 143.0},
                    "margens_br": {"ml": {"margem_brl": 38.0}},
                    "margens_china_maritimo": {"ml": {"margem_brl": -59.0}},
                }
            ],
        }
        linhas = src.formatar_secao_sourcing(sourcing, fmt_brl=lambda v: f"R$ {v}" if v else "n/d")
        texto = "\n".join(linhas)
        self.assertIn("Sourcing BR × China", texto)
        self.assertIn("COMPRAR_BR", texto)
        self.assertIn("PETG", texto)


if __name__ == "__main__":
    unittest.main()
