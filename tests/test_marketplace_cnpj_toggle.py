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


if __name__ == "__main__":
    unittest.main()
