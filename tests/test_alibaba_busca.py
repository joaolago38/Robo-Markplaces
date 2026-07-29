"""
tests/test_alibaba_busca.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.alibaba import busca


class TestAlibabaBuscaHelpers(unittest.TestCase):
    def test_montar_termo_prioriza_termo_busca(self):
        t = busca.montar_termo_busca({"termo_busca": "nail polish bottle", "nome": "X"})
        self.assertEqual(t, "nail polish bottle")

    def test_montar_termo_preferir_pt(self):
        with patch("core.config.ALIBABA_PREFERIR_TERMO_PT", True):
            t = busca.montar_termo_busca(
                {
                    "termo_busca": "PLA filament",
                    "termo_busca_pt": "filamento PLA",
                    "nome": "X",
                }
            )
            self.assertEqual(t, "filamento PLA")

    def test_termos_busca_produto_inclui_secundario(self):
        with patch("core.config.ALIBABA_BUSCAR_TERMO_SECUNDARIO", True), patch(
            "core.config.ALIBABA_PREFERIR_TERMO_PT", False
        ):
            termos = busca.termos_busca_produto(
                {
                    "termo_busca": "PLA filament wholesale",
                    "termo_busca_pt": "filamento PLA atacado",
                }
            )
            self.assertEqual(
                termos,
                ["PLA filament wholesale", "filamento PLA atacado"],
            )

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

    def test_e_oportunidade_moq_max_nao_exige_moq_parseado(self):
        """Com moq_max no catálogo, anúncio sem MOQ ainda pode ser oportunidade."""
        produto = {"moq_max": 1000}
        with patch.object(busca, "ALIBABA_EXIGIR_MOQ_PARA_OPORTUNIDADE", False):
            self.assertTrue(
                busca._e_oportunidade(produto, {"preco_usd": 0.2, "url": "http://x/product-detail/1"})
            )
            self.assertTrue(
                busca._e_oportunidade(produto, {"preco_usd": 0.2, "moq": 100, "url": "http://x"})
            )
            self.assertFalse(
                busca._e_oportunidade(produto, {"preco_usd": 0.2, "moq": 5000, "url": "http://x"})
            )

    def test_e_oportunidade_exige_moq_por_flag(self):
        with patch.object(busca, "ALIBABA_EXIGIR_MOQ_PARA_OPORTUNIDADE", True):
            self.assertFalse(busca._e_oportunidade({}, {"preco_usd": 0.2, "url": "http://x"}))
            self.assertTrue(busca._e_oportunidade({}, {"preco_usd": 0.2, "moq": 50, "url": "http://x"}))


class TestDetectarBloqueioAlibaba(unittest.TestCase):
    def test_captcha_sem_produto(self):
        html = "<html><body>" + ("x" * 900) + " captcha punish deny </body></html>"
        self.assertIsNotNone(busca.detectar_bloqueio_html_alibaba(html))
        self.assertIn("anti_bot", busca.detectar_bloqueio_html_alibaba(html) or "")

    def test_pagina_com_produto_nao_bloqueia(self):
        html = (
            "<html><body>"
            + ("x" * 900)
            + ' href="https://www.alibaba.com/product-detail/a_1.html" captcha'
            + "</body></html>"
        )
        self.assertIsNone(busca.detectar_bloqueio_html_alibaba(html))

    def test_html_vazio(self):
        self.assertEqual(busca.detectar_bloqueio_html_alibaba(""), "html_vazio")


class TestBuscarAlibabaDiretoPaginacao(unittest.TestCase):
    @patch.object(busca, "request")
    def test_pagina_multipla(self, mock_request):
        html_p1 = (
            '<a href="https://www.alibaba.com/product-detail/a_1111111111.html">A</a>'
            " US $1.00 MOQ: 10 "
        )
        html_p2 = (
            '<a href="https://www.alibaba.com/product-detail/b_2222222222.html">B</a>'
            " US $2.00 MOQ: 20 "
        )
        r1 = MagicMock(status_code=200, text=html_p1)
        r2 = MagicMock(status_code=200, text=html_p2)
        mock_request.side_effect = [r1, r2]

        with patch("core.config.ALIBABA_BUSCA_MAX_RESULTADOS", 40), patch(
            "core.config.ALIBABA_BUSCA_PAGINAS", 3
        ):
            itens = busca.buscar_alibaba_direto("PLA filament", max_resultados=10, paginas=2)

        self.assertGreaterEqual(len(itens), 2)
        self.assertEqual(mock_request.call_count, 2)
        self.assertIn("page=1", mock_request.call_args_list[0].args[1])
        self.assertIn("page=2", mock_request.call_args_list[1].args[1])

    @patch.object(busca, "request")
    def test_detalhado_marca_bloqueio_captcha(self, mock_request):
        html = "<html><head></head><body>" + ("z" * 1200) + " captcha punish </body></html>"
        mock_request.return_value = MagicMock(status_code=200, text=html)
        with patch("core.config.ALIBABA_BUSCA_MAX_RESULTADOS", 10), patch(
            "core.config.ALIBABA_BUSCA_PAGINAS", 2
        ):
            det = busca.buscar_alibaba_direto_detalhado("PLA", max_resultados=10, paginas=2)
        self.assertTrue(det["bloqueado"])
        self.assertEqual(det["itens"], [])
        self.assertIn("anti_bot", det.get("motivo") or "")
        self.assertEqual(mock_request.call_count, 1)


class TestBuscarOportunidades(unittest.TestCase):
    @patch.object(busca, "buscar_duckduckgo", return_value=[])
    @patch.object(busca, "buscar_alibaba_direto_detalhado")
    def test_retorna_novos_itens(self, mock_direto, _ddg):
        mock_direto.return_value = {
            "itens": [
                {
                    "url": "https://www.alibaba.com/product-detail/123.html",
                    "titulo": "nail polish bottle wholesale",
                    "snippet": "Trade Assurance MOQ 100",
                    "preco_usd": 0.25,
                    "moq": 100,
                    "fonte": "alibaba_search",
                }
            ],
            "bloqueado": False,
            "motivo": None,
            "paginas_ok": 1,
            "status_http": 200,
        }
        produto = {
            "termo_busca": "nail polish bottle",
            "preco_max_usd": 0.5,
            "moq_max": 5000,
        }
        out = busca.buscar_oportunidades(produto, pausa_seg=0)
        self.assertEqual(len(out), 1)
        self.assertIn("alibaba.com", out[0]["url"])

    @patch.object(busca, "buscar_duckduckgo", return_value=[])
    @patch.object(busca, "buscar_alibaba_direto_detalhado")
    def test_busca_termo_secundario(self, mock_direto, _ddg):
        mock_direto.side_effect = [
            {
                "itens": [
                    {
                        "url": "https://www.alibaba.com/product-detail/en_1.html",
                        "titulo": "PLA filament wholesale",
                        "snippet": "factory",
                        "preco_usd": 3.0,
                        "moq": 50,
                        "fonte": "alibaba_search",
                    }
                ],
                "bloqueado": False,
                "motivo": None,
                "paginas_ok": 1,
                "status_http": 200,
            },
            {
                "itens": [
                    {
                        "url": "https://www.alibaba.com/product-detail/pt_2.html",
                        "titulo": "filamento PLA atacado",
                        "snippet": "wholesale",
                        "preco_usd": 4.0,
                        "moq": 80,
                        "fonte": "alibaba_search",
                    }
                ],
                "bloqueado": False,
                "motivo": None,
                "paginas_ok": 1,
                "status_http": 200,
            },
        ]
        produto = {
            "termo_busca": "PLA filament wholesale",
            "termo_busca_pt": "filamento PLA atacado",
            "preco_max_usd": 10,
            "moq_max": 500,
        }
        with patch("core.config.ALIBABA_BUSCAR_TERMO_SECUNDARIO", True), patch(
            "core.config.ALIBABA_PREFERIR_TERMO_PT", False
        ), patch("core.config.DDG_ALIBABA_SKIP_SE_DIRETO", False), patch(
            "core.config.ALIBABA_BUSCA_MAX_RESULTADOS", 40
        ), patch("core.config.ALIBABA_BUSCA_PAGINAS", 1):
            out = busca.buscar_oportunidades(produto, pausa_seg=0)
        self.assertEqual(mock_direto.call_count, 2)
        self.assertEqual(len(out), 2)

    @patch.object(busca, "buscar_duckduckgo")
    @patch.object(busca, "buscar_alibaba_direto_detalhado")
    def test_ddg_nao_pula_com_poucos_diretos(self, mock_direto, mock_ddg):
        mock_direto.return_value = {
            "itens": [
                {
                    "url": "https://www.alibaba.com/product-detail/few_1.html",
                    "titulo": "PLA filament wholesale",
                    "snippet": "factory",
                    "preco_usd": 3.0,
                    "moq": 10,
                    "fonte": "alibaba_search",
                }
            ],
            "bloqueado": False,
            "motivo": None,
            "paginas_ok": 1,
            "status_http": 200,
        }
        mock_ddg.return_value = []
        produto = {"termo_busca": "PLA filament wholesale", "preco_max_usd": 10}
        with patch("core.config.DDG_ALIBABA_SKIP_SE_DIRETO", True), patch(
            "core.config.DDG_ALIBABA_MIN_DIRETO_PARA_PULAR", 12
        ), patch("core.config.ALIBABA_BUSCAR_TERMO_SECUNDARIO", False), patch(
            "core.config.ALIBABA_BUSCA_MAX_RESULTADOS", 40
        ), patch("core.config.ALIBABA_BUSCA_PAGINAS", 1):
            busca.buscar_oportunidades(produto, pausa_seg=0)
        mock_ddg.assert_called()

    @patch.object(busca, "buscar_duckduckgo", return_value=[])
    @patch.object(busca, "buscar_alibaba_direto_detalhado")
    def test_detalhado_propaga_bloqueio(self, mock_direto, _ddg):
        mock_direto.return_value = {
            "itens": [],
            "bloqueado": True,
            "motivo": "anti_bot:captcha+punish",
            "paginas_ok": 0,
            "status_http": 200,
        }
        out = busca.buscar_oportunidades_detalhado(
            {"termo_busca": "PLA filament"}, pausa_seg=0
        )
        self.assertEqual(out["oportunidades"], [])
        self.assertTrue(out["coleta"]["bloqueado"])
        self.assertIn("captcha", out["coleta"]["motivo"] or "")


if __name__ == "__main__":
    unittest.main()
