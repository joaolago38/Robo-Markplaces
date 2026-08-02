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
        self.assertEqual(ec.marketplace_foco(), "mercadolivre")

    def test_empresa_ativa_default_esmaltes(self):
        emp = ec.empresa_ativa()
        self.assertIsNotNone(emp)
        self.assertEqual(emp["id"], "esmaltes_impala")
        self.assertEqual(emp["marketplaces"]["foco_principal"], "mercadolivre")

    def test_masterprint_por_cnae(self):
        lista = ec.empresas_por_cnae("4751-2/01")
        self.assertTrue(any(e["id"] == "masterprint" for e in lista))
        self.assertEqual(ec.empresas_por_cnae(""), [])

    def test_masterprint_por_ramo(self):
        emp = ec.empresa_por_ramo("filamentos")
        self.assertIsNotNone(emp)
        self.assertEqual(emp["id"], "masterprint")
        self.assertIsNone(ec.empresa_por_ramo(""))
        self.assertIsNone(ec.empresa_por_id(""))

    def test_empresa_por_cnpj_invalido(self):
        self.assertIsNone(ec.empresa_por_cnpj("123"))
        self.assertIsNone(ec.empresa_por_cnpj(""))

    def test_formatar_cnpj(self):
        self.assertEqual(ec.formatar_cnpj("12345678000199"), "12.345.678/0001-99")
        self.assertEqual(ec.formatar_cnpj("123"), "123")

    def test_norm_marketplace_aliases(self):
        self.assertEqual(ec._norm_marketplace("ML"), "mercadolivre")
        self.assertEqual(ec._norm_marketplace("magazinevoce"), "magalu")

    def test_contexto_analise_inclui_cnae_e_foco_ml(self):
        ctx = ec.contexto_analise(ramo="masterprint")
        self.assertTrue(ctx["ok"])
        self.assertTrue(ctx["prioriza_mercadolivre"])
        self.assertEqual(ctx["foco_marketplace"], "mercadolivre")
        self.assertTrue(ctx["cnaes"])
        self.assertEqual(ctx["cnae_principal"]["codigo"], "4751-2/01")

    def test_contexto_por_empresa_id(self):
        ctx = ec.contexto_analise(empresa_id="esmaltes_impala")
        self.assertTrue(ctx["ok"])
        self.assertEqual(ctx["empresa"]["id"], "esmaltes_impala")

    @patch("core.empresa_contexto.EMPRESA_ATIVA_ID", "masterprint")
    def test_override_empresa_ativa_id(self):
        ec.limpar_cache_empresas()
        emp = ec.empresa_ativa()
        self.assertEqual(emp["id"], "masterprint")

    @patch("core.empresa_contexto.EMPRESA_ATIVA_CNPJ", "00000000000191")
    @patch("core.empresa_contexto.empresa_por_cnpj")
    def test_override_empresa_ativa_cnpj(self, mock_cnpj):
        mock_cnpj.return_value = {
            "id": "via_cnpj",
            "nome_fantasia": "X",
            "cnpj": "00000000000191",
            "cnpj_formatado": "00.000.000/0001-91",
            "cnaes": [],
            "cnae_principal": None,
            "marketplaces": {"foco_principal": "mercadolivre"},
            "ml": {},
            "telegram_gestor_chat_id": "",
            "ramos": [],
            "agentes_prioritarios": [],
            "prioriza_mercadolivre": True,
        }
        ec.limpar_cache_empresas()
        emp = ec.empresa_ativa()
        self.assertEqual(emp["id"], "via_cnpj")

    def test_linha_telegram(self):
        txt = ec.linha_empresa_telegram(ec.empresa_por_id("esmaltes_impala"))
        self.assertIn("Empresa:", txt)
        self.assertIn("Mercado Livre", txt)
        self.assertIn("CNAE", txt)
        self.assertIn("Empresa:", ec.linha_empresa_telegram(None))

    @patch("core.empresa_contexto.ML_SELLER_ID", "111")
    @patch("core.empresa_contexto.TELEGRAM_GESTOR_CHAT_ID", "-100")
    def test_aplicar_overrides_esmaltes(self):
        emp = ec.empresa_por_id("esmaltes_impala")
        out = ec._aplicar_overrides_env(dict(emp))
        self.assertEqual(out["ml"]["seller_id"], "111")
        self.assertEqual(out["telegram_gestor_chat_id"], "-100")


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


class TestCustosPetgExtras(unittest.TestCase):
    def setUp(self):
        from integracoes.filamentos import custos_masterprint_petg as custos

        custos.limpar_cache_custos()

    def test_padrao_quando_titulo_sem_cor(self):
        from integracoes.filamentos import custos_masterprint_petg as custos

        m = custos.casar_custo_anuncio("Filamento PETG Masterprint 1kg")
        self.assertIsNotNone(m)
        self.assertIn(m["match"], ("custo_padrao_1kg", "sku_tabela"))

    def test_escala_peso_3kg(self):
        from integracoes.filamentos import custos_masterprint_petg as custos

        m = custos.casar_custo_anuncio("Filamento PETG Masterprint Preto 3kg")
        self.assertIsNotNone(m)
        self.assertEqual(m["peso_kg"], 3.0)


if __name__ == "__main__":
    unittest.main()
