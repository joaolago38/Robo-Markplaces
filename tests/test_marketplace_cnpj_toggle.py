"""tests/test_marketplace_cnpj_toggle.py — identidade CNPJ + toggle de operação."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.marketplace_algorithm import avaliar_marketplace
from core.marketplace_cnpj import identificar_cnpj_conectado, linha_cnpj_telegram
from core.marketplace_toggle import canal_em_operacao, definir_canal, estado_canais


class TestMarketplaceToggle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = Path(self._tmp.name) / "marketplaces_operacao.json"
        self._p = patch("core.marketplace_toggle.TOGGLE_PATH", self._path)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def test_shopee_off_por_padrao(self):
        self.assertFalse(canal_em_operacao("shopee"))
        self.assertTrue(canal_em_operacao("mercadolivre"))

    def test_ligar_shopee_via_arquivo(self):
        definir_canal("shopee", True, motivo="homologado")
        self.assertTrue(canal_em_operacao("shopee"))
        st = estado_canais()
        self.assertTrue(st["canais"]["shopee"]["operando"])

    def test_env_desliga_mesmo_com_arquivo_on(self):
        definir_canal("amazon", True)
        with patch.dict(os.environ, {"MARKETPLACE_AMAZON_OPERANDO": "0"}, clear=False):
            self.assertFalse(canal_em_operacao("amazon"))


class TestIdentificarCnpj(unittest.TestCase):
    def test_sem_conta_nao_identifica(self):
        with patch("core.marketplace_cnpj._conta_id_env", return_value=""):
            out = identificar_cnpj_conectado("shopee", conta_id="")
        self.assertFalse(out["identificado"])
        self.assertIn("vazia", out["motivo"])

    def test_casa_impala_pelo_shop_id(self):
        emp_impala = {
            "id": "esmaltes_impala",
            "cnpj": "52668583000127",
            "cnpj_formatado": "52.668.583/0001-27",
            "nome_fantasia": "Impala",
            "shopee": {"shop_id": "111"},
            "ml": {"seller_id": ""},
            "magalu": {},
            "amazon": {},
        }
        emp_mp = {
            "id": "masterprint",
            "cnpj": "23811261000197",
            "cnpj_formatado": "23.811.261/0001-97",
            "nome_fantasia": "Masterprint",
            "shopee": {"shop_id": "222"},
            "ml": {"seller_id": ""},
            "magalu": {},
            "amazon": {},
        }
        with patch("core.empresa.catalogo.listar_empresas", return_value=[emp_impala, emp_mp]):
            with patch("core.empresa.overrides.aplicar_overrides_env", side_effect=lambda e: e):
                out = identificar_cnpj_conectado("shopee", conta_id="111")
        self.assertTrue(out["identificado"])
        self.assertEqual(out["empresa_id"], "esmaltes_impala")
        self.assertIn("Impala", linha_cnpj_telegram(out))

    def test_ambiguo_mesma_conta_dois_cnpjs(self):
        emp_a = {
            "id": "esmaltes_impala",
            "cnpj": "52668583000127",
            "cnpj_formatado": "52.668.583/0001-27",
            "nome_fantasia": "Impala",
            "ml": {"seller_id": "999"},
            "shopee": {},
            "magalu": {},
            "amazon": {},
        }
        emp_b = {
            "id": "masterprint",
            "cnpj": "23811261000197",
            "cnpj_formatado": "23.811.261/0001-97",
            "nome_fantasia": "Masterprint",
            "ml": {"seller_id": "999"},
            "shopee": {},
            "magalu": {},
            "amazon": {},
        }
        with patch("core.empresa.catalogo.listar_empresas", return_value=[emp_a, emp_b]):
            with patch("core.empresa.overrides.aplicar_overrides_env", side_effect=lambda e: e):
                out = identificar_cnpj_conectado("mercadolivre", conta_id="999")
        self.assertTrue(out["ambiguo"])
        self.assertIn("AMBÍGUO", linha_cnpj_telegram(out))


class TestAlgoritmoPorCanal(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._history = Path(self._tmpdir.name) / "h.json"
        self._p = patch("core.marketplace_algorithm.HISTORY_FILE", self._history)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmpdir.cleanup()

    def test_shopee_chat_pesa_mais_que_ml(self):
        metrics = {
            "configurado": True,
            "api_ok": True,
            "pendencias": 4,
            "claims_rate": None,
            "claims_conhecido": False,
            "dias_sem_acesso": 0,
        }
        sh = avaliar_marketplace("shopee", metrics)
        ml = avaliar_marketplace("mercadolivre", {**metrics, "claims_conhecido": True, "claims_rate": 0.0})
        self.assertLess(sh["score"], ml["score"])
        self.assertTrue(any("Shopee" in p or "chat" in p.lower() for p in sh["penalidades"]))

    def test_amazon_fila_leve_e_claims_nao_fingem_zero(self):
        out = avaliar_marketplace(
            "amazon",
            {
                "configurado": True,
                "api_ok": True,
                "pendencias": 20,
                "claims_rate": None,
                "claims_conhecido": False,
                "dias_sem_acesso": 0,
                "estoque_sync": False,
            },
        )
        self.assertGreaterEqual(out["score"], 60)
        self.assertTrue(any("não medido" in p for p in out["penalidades"]))
        self.assertTrue(any("Buy Box" in a or "estoque" in a.lower() for a in out["acoes_recomendadas"]))

    def test_ml_claims_reais_penalizam(self):
        out = avaliar_marketplace(
            "mercadolivre",
            {
                "configurado": True,
                "api_ok": True,
                "pendencias": 0,
                "claims_rate": 0.03,
                "claims_conhecido": True,
                "dias_sem_acesso": 0,
            },
        )
        self.assertLess(out["score"], 80)
        self.assertEqual(out["modelo"], "mercadolivre")


class TestPublicacaoDoisCnpjs(unittest.TestCase):
    def test_esmalte_nao_publica_na_masterprint(self):
        from core.empresa.publicacao_cnpj import autorizar_publicacao

        out = autorizar_publicacao(
            "IMP-MIMO-003",
            empresa_id="masterprint",
            veredito="liberado",
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "cnpj_errado")

    def test_petg_nao_publica_na_impala(self):
        from core.empresa.publicacao_cnpj import autorizar_publicacao

        out = autorizar_publicacao(
            "231020001",
            empresa_id="esmaltes_impala",
            veredito="liberado",
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "cnpj_errado")

    def test_masterprint_bloqueada_ate_ruptura(self):
        from core.empresa.publicacao_cnpj import autorizar_publicacao

        out = autorizar_publicacao("231020001", veredito="ainda_nao")
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "ruptura_impala")
        aprox = autorizar_publicacao("231020001", veredito="aproximando")
        self.assertEqual(aprox["motivo"], "ruptura_impala")

    def test_nao_grava_seller_da_impala(self):
        from core.empresa.contas_masterprint import gravar_contas_distintas
        from core.empresa.overrides import aplicar_overrides_env
        from core.empresa.catalogo import empresa_por_id

        with patch.dict(os.environ, {"MASTERPRINT_ML_SELLER_ID": "1651424153"}, clear=False):
            mp = aplicar_overrides_env(empresa_por_id("masterprint") or {})
            self.assertFalse(str((mp.get("ml") or {}).get("seller_id") or ""))
            with tempfile.TemporaryDirectory() as tmp:
                cat = Path(tmp) / "empresas.json"
                ramo = Path(tmp) / "ramo.json"
                cat.write_text(
                    '{"empresas":[{"id":"esmaltes_impala","ml":{"seller_id":"1651424153"},'
                    '"shopee":{},"magalu":{},"amazon":{}},'
                    '{"id":"masterprint","ml":{"seller_id":""},"shopee":{},"magalu":{},"amazon":{}}]}',
                    encoding="utf-8",
                )
                ramo.write_text('{"ml_seller_id":""}', encoding="utf-8")
                rec = gravar_contas_distintas(cat, ramo)
                texto = cat.read_text(encoding="utf-8")
        self.assertIn("mercadolivre", rec["recusados"])
        self.assertEqual(rec["gravados"], {})
        self.assertNotIn("1651424153", texto.split("masterprint")[-1])

    def test_grava_seller_distinto_e_libera_publicacao(self):
        from core.empresa.contas_masterprint import gravar_contas_distintas
        from core.empresa.publicacao_cnpj import autorizar_publicacao

        env = {
            "MASTERPRINT_ML_SELLER_ID": "888777",
            "ML_ACCESS_TOKEN_MASTERPRINT": "tok-mp",
            "MASTERPRINT_ML_NICKNAME": "LOJA_MP",
        }
        with patch.dict(os.environ, env, clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                cat = Path(tmp) / "empresas.json"
                ramo = Path(tmp) / "ramo.json"
                cat.write_text(
                    '{"empresas":[{"id":"esmaltes_impala","ml":{"seller_id":"1651424153"}},'
                    '{"id":"masterprint","ml":{"seller_id":"","nickname":""}}]}',
                    encoding="utf-8",
                )
                ramo.write_text('{"ml_seller_id":"","ml_nickname":""}', encoding="utf-8")
                rec = gravar_contas_distintas(cat, ramo)
                self.assertEqual(rec["gravados"].get("mercadolivre"), "888777")
                gravado = cat.read_text(encoding="utf-8")
                self.assertIn("888777", gravado)
                self.assertIn("LOJA_MP", gravado)
                self.assertEqual(
                    __import__("json").loads(ramo.read_text(encoding="utf-8"))["ml_seller_id"],
                    "888777",
                )
            out = autorizar_publicacao("231020001", veredito="liberado")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["empresa_id"], "masterprint")
        self.assertEqual(out["conta_id"], "888777")
        self.assertTrue(out["token_presente"])

    def test_mesmo_seller_nos_dois_cnpjs_bloqueia_publicacao(self):
        from core.empresa.publicacao_cnpj import autorizar_publicacao

        empresas = [
            {
                "id": "esmaltes_impala",
                "cnpj": "52668583000127",
                "nome_fantasia": "Impala",
                "ml": {"seller_id": "999"},
                "shopee": {},
                "magalu": {},
                "amazon": {},
                "ramos": ["esmaltes"],
                "cnaes": [{"codigo": "4772-5/00", "codigo_norm": "4772500", "principal": True}],
            },
            {
                "id": "masterprint",
                "cnpj": "23811261000197",
                "nome_fantasia": "Masterprint",
                "ml": {"seller_id": "999"},
                "shopee": {},
                "magalu": {},
                "amazon": {},
                "ramos": ["petg", "filamentos"],
                "cnaes": [{"codigo": "4689-3/02", "codigo_norm": "4689302", "principal": False}],
            },
        ]
        with patch("core.empresa.catalogo.listar_empresas", return_value=empresas):
            with patch("core.empresa.overrides.aplicar_overrides_env", side_effect=lambda e: e):
                out = autorizar_publicacao("231020001", veredito="liberado")
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "conta_compartilhada")

    def test_escopo_ml_usa_token_da_masterprint(self):
        from core.marketplace_cnpj import usar_conta
        from integracoes.ml import ml_client

        cred = {
            "empresa_id": "masterprint",
            "marketplace": "mercadolivre",
            "conta_id": "888777",
            "access_token": "tok-mp",
        }
        with usar_conta(cred):
            self.assertEqual(ml_client.seller_id_ativo(), "888777")
            self.assertEqual(ml_client.token_ativo(), "tok-mp")
        self.assertNotEqual(ml_client.seller_id_ativo(), "888777")


if __name__ == "__main__":
    unittest.main()
