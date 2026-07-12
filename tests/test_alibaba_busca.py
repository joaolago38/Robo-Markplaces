"""
tests/test_alibaba_busca.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.alibaba import busca


class TestAlibabaBuscaHelpers(unittest.TestCase):
    def test_montar_termo_prioriza_termo_busca(self):
        t = busca.montar_termo_busca({"termo_busca": "nail polish bottle", "nome": "X"})
        self.assertEqual(t, "nail polish bottle")

    def test_extrair_preco_usd(self):
        self.assertAlmostEqual(busca._extrair_preco_usd("from US $0.28 / piece"), 0.28)

    def test_extrair_preco_usd_virgula_decimal(self):
        self.assertAlmostEqual(busca._extrair_preco_usd("US $0,28 / piece"), 0.28)
        self.assertAlmostEqual(busca._extrair_preco_usd("USD 1,50"), 1.50)

    def test_extrair_moq(self):
        self.assertEqual(busca._extrair_moq("MOQ: 500 pieces"), 500)

    def test_normalizar_url_alibaba_corrige_id_colado(self):
        quebrada = "alibaba.com/product-detail/Wholesale-PLA-Filament-1-75mm-1kg1601242225300.html"
        corrigida = busca.normalizar_url_alibaba(quebrada)
        self.assertIn("1kg_1601242225300", corrigida)
        self.assertTrue(corrigida.startswith("https://www.alibaba.com/"))

    def test_normalizar_url_preserva_url_valida(self):
        url = "https://shenzhen-abc.en.alibaba.com/product-detail/Item-Name_1234567890.html"
        self.assertEqual(busca.normalizar_url_alibaba(url), url)

    def test_montar_url_busca_alibaba(self):
        url = busca.montar_url_busca_alibaba("PLA filament 1.75mm")
        self.assertIn("SearchText=PLA", url)
        self.assertIn("alibaba.com/trade/search", url)

    def test_extrair_distribuidor_do_snippet(self):
        nome = busca._extrair_distribuidor(
            "PLA filament by Shenzhen ABC Technology Co., Ltd. MOQ 100",
        )
        self.assertIn("Shenzhen ABC", nome or "")

    def test_extrair_distribuidor_da_url(self):
        nome = busca._extrair_distribuidor(
            "",
            url="https://shenzhen-abc-tech.en.alibaba.com/product-detail/123.html",
        )
        self.assertEqual(nome, "Shenzhen Abc Tech")

    def test_enriquecer_distribuidor(self):
        item = busca._enriquecer_distribuidor(
            {
                "url": "https://xyz-filament.en.alibaba.com/product-detail/1.html",
                "titulo": "PLA filament",
                "snippet": "wholesale factory",
            }
        )
        self.assertEqual(item.get("distribuidor"), "Xyz Filament")

    def test_e_oportunidade_respeita_preco_max(self):
        produto = {"preco_max_usd": 0.5}
        self.assertTrue(busca._e_oportunidade(produto, {"preco_usd": 0.3, "url": "http://x"}))
        self.assertFalse(busca._e_oportunidade(produto, {"preco_usd": 0.9, "url": "http://x"}))

    def test_e_oportunidade_exige_moq_quando_moq_max(self):
        produto = {"moq_max": 1000}
        self.assertFalse(busca._e_oportunidade(produto, {"preco_usd": 0.2, "url": "http://x"}))
        self.assertTrue(busca._e_oportunidade(produto, {"preco_usd": 0.2, "moq": 100, "url": "http://x"}))
        self.assertFalse(busca._e_oportunidade(produto, {"preco_usd": 0.2, "moq": 5000, "url": "http://x"}))

    def test_e_oportunidade_exige_moq_por_flag(self):
        with patch.object(busca, "ALIBABA_EXIGIR_MOQ_PARA_OPORTUNIDADE", True):
            self.assertFalse(busca._e_oportunidade({}, {"preco_usd": 0.2, "url": "http://x"}))
            self.assertTrue(busca._e_oportunidade({}, {"preco_usd": 0.2, "moq": 50, "url": "http://x"}))


class TestBuscarOportunidades(unittest.TestCase):
    @patch.object(busca, "buscar_duckduckgo", return_value=[])
    @patch.object(busca, "buscar_alibaba_direto")
    def test_retorna_novos_itens(self, mock_direto, _ddg):
        mock_direto.return_value = [
            {
                "url": "https://www.alibaba.com/product-detail/123.html",
                "titulo": "nail polish bottle wholesale",
                "snippet": "Trade Assurance MOQ 100",
                "preco_usd": 0.25,
                "moq": 100,
                "fonte": "alibaba_search",
            }
        ]
        produto = {
            "termo_busca": "nail polish bottle",
            "preco_max_usd": 0.5,
            "moq_max": 5000,
        }
        out = busca.buscar_oportunidades(produto, pausa_seg=0)
        self.assertEqual(len(out), 1)
        self.assertIn("alibaba.com", out[0]["url"])


if __name__ == "__main__":
    unittest.main()
