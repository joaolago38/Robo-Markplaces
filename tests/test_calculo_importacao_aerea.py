"""
tests/test_calculo_importacao_aerea.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.importacao.calculo_importacao_aerea import (
    calcular_custo_importacao_aerea_formal,
    exportar_csv_resultado,
    icms_pct_por_uf,
    montar_entradas_de_produto,
)


class CalculoImportacaoAereaTests(unittest.TestCase):
    def test_icms_sp(self):
        self.assertEqual(icms_pct_por_uf("SP"), 18.0)

    def test_calculo_cascata_basico(self):
        entradas = {
            "fob_usd": 10.0,
            "peso_bruto_kg": 1.0,
            "frete_aereo_usd": 50.0,
            "seguro_pct": 0.5,
            "cambio_usd_brl": 5.0,
            "ii_pct": 16.0,
            "ipi_pct": 0.0,
            "pis_cofins_pct": 11.75,
            "icms_pct": 18.0,
            "uf_destino": "SP",
            "quantidade": 10,
            "armazenagem_brl": 450.0,
            "desembaraco_brl": 1200.0,
            "thc_brl": 380.0,
            "siscomex_brl": 214.5,
            "frete_rodoviario_brl": 650.0,
        }
        out = calcular_custo_importacao_aerea_formal(entradas)
        self.assertTrue(out["ok"])
        self.assertGreater(out["valor_aduaneiro_cif_brl"], 0)
        self.assertGreater(out["ii_brl"], 0)
        self.assertGreater(out["icms_brl"], 0)
        self.assertGreater(out["custo_total_brl"], out["valor_aduaneiro_cif_brl"])
        self.assertEqual(out["custo_unitario_brl"], round(out["custo_total_brl"] / 10, 2))
        self.assertEqual(len(out["itens"]), 12)

    def test_icms_por_dentro(self):
        entradas = {
            "fob_usd": 100.0,
            "peso_bruto_kg": 1.0,
            "frete_aereo_usd": 0.0,
            "seguro_pct": 0.0,
            "cambio_usd_brl": 1.0,
            "ii_pct": 0.0,
            "ipi_pct": 0.0,
            "pis_cofins_pct": 0.0,
            "icms_pct": 18.0,
            "uf_destino": "SP",
            "quantidade": 1,
            "armazenagem_brl": 0.0,
            "desembaraco_brl": 0.0,
            "thc_brl": 0.0,
            "siscomex_brl": 0.0,
            "frete_rodoviario_brl": 0.0,
        }
        out = calcular_custo_importacao_aerea_formal(entradas)
        base = 100.0
        icms_esperado = (0.18 * base) / (1 - 0.18)
        self.assertAlmostEqual(out["icms_brl"], round(icms_esperado, 2), places=1)

    def test_montar_entradas_produto(self):
        produto = {
            "id": "p1",
            "nome": "PLA",
            "peso_kg": 1.2,
            "ncm": "39169090",
            "ii_pct": 12.0,
            "moq_referencia": 50,
        }
        op = {"preco_usd": 4.5, "moq": 50}
        ent = montar_entradas_de_produto(produto, op, cambio_usd_brl=5.5)
        self.assertEqual(ent["quantidade"], 50)
        self.assertEqual(ent["fob_usd"], 4.5)
        self.assertEqual(ent["ii_pct"], 12.0)

    def test_exportar_csv(self):
        out = calcular_custo_importacao_aerea_formal(
            {
                "fob_usd": 5.0,
                "peso_bruto_kg": 1.0,
                "frete_aereo_usd": 20.0,
                "seguro_pct": 0.5,
                "cambio_usd_brl": 5.0,
                "ii_pct": 16.0,
                "ipi_pct": 0.0,
                "pis_cofins_pct": 11.75,
                "icms_pct": 18.0,
                "uf_destino": "SP",
                "quantidade": 1,
                "armazenagem_brl": 100.0,
                "desembaraco_brl": 100.0,
                "thc_brl": 100.0,
                "siscomex_brl": 100.0,
                "frete_rodoviario_brl": 100.0,
            }
        )
        csv = exportar_csv_resultado(out)
        self.assertIn("custo_total_brl", csv)
        self.assertIn("FOB mercadoria", csv)

    @patch("integracoes.importacao.perfil_empresa_importacao.request")
    def test_perfil_cnpj_brasilapi(self, mock_req):
        from integracoes.importacao.perfil_empresa_importacao import buscar_empresa_por_cnpj

        class Resp:
            status_code = 200

            def json(self):
                return {
                    "cnpj": "52668583000127",
                    "razao_social": "EMPRESA TESTE LTDA",
                    "logradouro": "Rua A",
                    "numero": "100",
                    "municipio": "Campinas",
                    "uf": "SP",
                    "opcao_pelo_simples": False,
                }

        mock_req.return_value = Resp()
        out = buscar_empresa_por_cnpj("52.668.583/0001-27")
        self.assertTrue(out["ok"])
        self.assertEqual(out["razao_social"], "EMPRESA TESTE LTDA")

    def test_perfil_cnpj_invalido(self):
        from integracoes.importacao.perfil_empresa_importacao import buscar_empresa_por_cnpj

        out = buscar_empresa_por_cnpj("123")
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "CNPJ inválido")

    @patch("integracoes.importacao.perfil_empresa_importacao.request")
    def test_perfil_receitaws_fallback(self, mock_req):
        from integracoes.importacao.perfil_empresa_importacao import buscar_empresa_por_cnpj

        class RespBrasil:
            status_code = 500

            def json(self):
                return {}

        class RespReceita:
            status_code = 200

            def json(self):
                return {
                    "cnpj": "52668583000127",
                    "nome": "EMPRESA RECEITA LTDA",
                    "logradouro": "Rua B",
                    "numero": "200",
                    "municipio": "Americana",
                    "uf": "SP",
                    "simples": "nao",
                }

        mock_req.side_effect = [RespBrasil(), RespReceita()]
        out = buscar_empresa_por_cnpj("52668583000127")
        self.assertTrue(out["ok"])
        self.assertEqual(out["fonte"], "receitaws")

    @patch("integracoes.importacao.perfil_empresa_importacao.buscar_empresa_por_cnpj")
    def test_obter_perfil_importador(self, mock_busca):
        from integracoes.importacao.perfil_empresa_importacao import obter_perfil_importador

        mock_busca.return_value = {
            "ok": True,
            "razao_social": "API LTDA",
            "endereco": "Rua X",
            "regime_tributario": "lucro_presumido",
            "fonte": "brasilapi",
        }
        out = obter_perfil_importador()
        self.assertTrue(out["ok"])
        self.assertEqual(out["razao_social"], "API LTDA")
        self.assertEqual(out["fonte_empresa"], "brasilapi")

    def test_fob_invalido(self):
        out = calcular_custo_importacao_aerea_formal({"fob_usd": 0, "cambio_usd_brl": 5})
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
