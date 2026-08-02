"""tests/test_empresa_contexto.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core import empresa_contexto as ec


class TestEmpresaContexto(unittest.TestCase):
    def setUp(self):
        ec.limpar_cache_empresas()

    def test_catalogo_carrega_duas_empresas(self):
        empresas = ec.listar_empresas()
        ids = {e["id"] for e in empresas}
        self.assertIn("esmaltes_impala", ids)
        self.assertIn("masterprint", ids)

    def test_foco_padrao_mercadolivre(self):
        cat = ec.carregar_catalogo()
        self.assertEqual(cat["foco_marketplace_padrao"], "mercadolivre")
        self.assertTrue(ec.prioriza_mercadolivre())

    def test_empresa_ativa_default_esmaltes(self):
        emp = ec.empresa_ativa()
        self.assertIsNotNone(emp)
        self.assertEqual(emp["id"], "esmaltes_impala")
        self.assertEqual(emp["marketplaces"]["foco_principal"], "mercadolivre")

    def test_masterprint_por_cnae(self):
        lista = ec.empresas_por_cnae("4751-2/01")
        self.assertTrue(any(e["id"] == "masterprint" for e in lista))

    def test_masterprint_por_ramo(self):
        emp = ec.empresa_por_ramo("filamentos")
        self.assertIsNotNone(emp)
        self.assertEqual(emp["id"], "masterprint")

    def test_contexto_analise_inclui_cnae_e_foco_ml(self):
        ctx = ec.contexto_analise(ramo="masterprint")
        self.assertTrue(ctx["ok"])
        self.assertTrue(ctx["prioriza_mercadolivre"])
        self.assertEqual(ctx["foco_marketplace"], "mercadolivre")
        self.assertTrue(ctx["cnaes"])
        self.assertEqual(ctx["cnae_principal"]["codigo"], "4751-2/01")

    @patch("core.empresa_contexto.EMPRESA_ATIVA_ID", "masterprint")
    def test_override_empresa_ativa_id(self):
        ec.limpar_cache_empresas()
        emp = ec.empresa_ativa()
        self.assertEqual(emp["id"], "masterprint")

    def test_linha_telegram(self):
        txt = ec.linha_empresa_telegram(ec.empresa_por_id("esmaltes_impala"))
        self.assertIn("Empresa:", txt)
        self.assertIn("Mercado Livre", txt)
        self.assertIn("CNAE", txt)


class TestRamoUsaEmpresaSemQuebrarEnv(unittest.TestCase):
    def setUp(self):
        from integracoes.masterprint import ramo as ramo_mod

        ramo_mod.limpar_cache_ramo()
        ec.limpar_cache_empresas()

    def test_ramo_traz_cnae_do_catalogo_empresa(self):
        from integracoes.masterprint.ramo import carregar_ramo, linha_identidade_telegram

        r = carregar_ramo()
        self.assertEqual(r.get("empresa_id"), "masterprint")
        self.assertIsNotNone(r.get("cnae_principal"))
        self.assertEqual(r["foco_marketplace"], "mercadolivre")
        linha = linha_identidade_telegram(r)
        self.assertIn("CNAE", linha)
        self.assertIn("foco *ML*", linha)

    @patch("integracoes.masterprint.ramo.MASTERPRINT_CNPJ", "11222333000181")
    def test_env_masterprint_cnpj_tem_prioridade(self):
        from integracoes.masterprint import ramo as ramo_mod

        ramo_mod.limpar_cache_ramo()
        r = ramo_mod.carregar_ramo()
        self.assertEqual(r["cnpj"], "11222333000181")


if __name__ == "__main__":
    unittest.main()
