"""
tests/test_veiculos_scrapers.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.veiculos import scrapers as sc


class VeiculosScrapersTests(unittest.TestCase):
    def test_parse_preco_brl(self):
        self.assertEqual(sc.parse_preco_brl("R$ 13.500,00"), 13500.0)
        self.assertIsNone(sc.parse_preco_brl("Vendido"))
        self.assertIsNone(sc.parse_preco_brl("PRÉ-LIBERAÇÃO"))

    def test_hash_anuncio(self):
        h1 = sc._hash_anuncio("lucineia", "123")
        h2 = sc._hash_anuncio("lucineia", "123")
        self.assertEqual(h1, h2)

    @patch("integracoes.veiculos.scrapers.request")
    def test_coletar_lucineia(self, mock_req):
        html = """
        <div class="card-body p-2 mr-1">
          <h5 class="card-text alert-link">Uno Mille 1.0</h5>
          <p class="card-text">
            <small>
              Marca: Fiat<br />
              Ano: 2011 / 2012 <br />
            </small>
          </p>
          <h5 class="card-text alert-link text-right">R$ 13.500,00</h5>
          <a href="Veiculo.aspx?id=123">VER MAIS</a>
        </div>
        """
        mock_req.return_value = MagicMock(status_code=200, text=html)
        itens = sc.coletar_lucineia()
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["marca"], "Fiat")

    @patch("integracoes.veiculos.scrapers.request")
    def test_coletar_lucineia_http_erro(self, mock_req):
        mock_req.return_value = MagicMock(status_code=500, text="")
        self.assertEqual(sc.coletar_lucineia(), [])

    def test_parse_leopardo_bloco(self):
        html = """
        <div class="col-list-3 divlinkclicable " id='divveiculo8628' data-identity='8628'>
        <div class="car-title-m">
        <h6 class='titulo-veiculo-card'><a href="https://www.leopardoveiculos.com.br/veiculo/fox/8628">VW FOX 1.0</a></h6>
        <span class='pull-left text-bold'>2008/2009</span>
        <span class="price">R$ 12.000,00</span>
        </div></div></div></div>
        """
        itens = sc._parse_leopardo_html(html, {"id": "leopardo", "nome": "Leopardo"})
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["preco"], 12000.0)

    @patch("integracoes.veiculos.scrapers.request")
    def test_coletar_leopardo(self, mock_req):
        page = '<meta name="csrf-token" content="tok123">'
        ajax = MagicMock(status_code=200)
        ajax.json.return_value = {
            "returnhtml": """
            <div class="col-list-3 divlinkclicable " id='divveiculo1' data-identity='1'>
            <h6 class='titulo-veiculo-card'><a href="https://www.leopardoveiculos.com.br/veiculo/gol/1">VW GOL 1.0</a></h6>
            <span class='pull-left text-bold'>2010/2011</span>
            <span class="price">R$ 9.000,00</span>
            </div></div></div></div>
            """,
            "retornopagina": -1,
        }
        mock_req.side_effect = [MagicMock(status_code=200, text=page), ajax]
        itens = sc.coletar_leopardo(max_paginas=1)
        self.assertEqual(len(itens), 1)

    def test_coletar_fonte_desconhecida(self):
        self.assertEqual(sc.coletar_fonte({"id": "x", "tipo": "outro"}), [])

    def test_coletar_motorjan(self):
        html = """
        <div class="offer_item clearfix">
        <a href=/veiculos/carro/10033/ford title="Ford Gol">
        <h2><a href=/veiculos/carro/10033/ford>Ford Gol 1.0</a></h2>
        <p>Modelo 2012</p>
        <span class=offer_miliage>CÓDIGO: 10033</span>
        <div class=offer_price>R$ 18.500,00</div>
        </div></div></div>
        """
        with patch("integracoes.veiculos.scrapers.request") as mock_req:
            mock_req.return_value = type("R", (), {"status_code": 200, "text": html})()
            itens = sc.coletar_motorjan()
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["preco"], 18500.0)

    def test_coletar_motorjan_html_sem_aspas(self):
        html = """
        <div class=offer_item clearfix>
        <a href=/veiculos/carro/10033/ford title="Ford Gol">
        <h2><a href=/veiculos/carro/10033/ford>Ford Gol 1.0</a></h2>
        <p>Modelo 2012</p>
        <span class=offer_miliage>CÓDIGO: 10033</span>
        <div class=offer_price>R$ 18.500,00</div>
        </div></div></div>
        """
        with patch("integracoes.veiculos.scrapers.request") as mock_req:
            mock_req.return_value = type("R", (), {"status_code": 200, "text": html})()
            itens = sc.coletar_motorjan()
        self.assertEqual(len(itens), 1)

    @patch("integracoes.veiculos.scrapers.request")
    def test_coletar_velozes(self, mock_req):
        home = '<a href="https://velozesbatidos.com.br/product/gol-2012/">x</a>'
        produto = (
            '<h1 class="product_title entry-title">VW GOL 1.0 2012</h1>'
            '<span class="woocommerce-Price-amount amount">R$ 15.000,00</span>'
        )
        mock_req.side_effect = [
            type("R", (), {"status_code": 200, "text": home})(),
            type("R", (), {"status_code": 200, "text": produto})(),
        ]
        itens = sc.coletar_velozes(max_produtos=1)
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["preco"], 15000.0)
        self.assertIn("GOL", itens[0]["titulo"])

    def test_parse_esperanca(self):
        html = """
        <li class="imvl-vertical pr radius4 ajsestoquie">
            <div class="fl hover-destaque border-car">
                <a href="http://www.esperancabatidos.com.br/Fiat-/-TITANO/2184" class="fl opacity" title="Fiat - TITANO">
                    <span class="box-cod-des radius4">COD. 2184</span>
                    <img src="./fotos/2184/x.jpg" alt="Fiat"/>
                </a>
            </div>
            <div class="fl pr itens-dest-secundario">
                <h1 class="fl w100">Fiat - TITANO RANCH 4X4</h1>
                <h2 class="fl w100">Cor: PRETA / Ano: 2025 0KM</h2>
                <h2 class="fl w100">R$ 219.900,00</h2>
            </div>
        </li>
        """
        with patch("integracoes.veiculos.scrapers.request") as mock_req:
            mock_req.return_value = MagicMock(status_code=200, text=html)
            itens = sc.coletar_esperanca()
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["preco"], 219900.0)
        self.assertEqual(itens[0]["id_externo"], "2184")

    def test_parse_007_batidos(self):
        html = """
        Comparar Veiculo Cod. 1707
        <h1>HYUNDAI</h1>
        <h2>Creta 2.0 prestige auto</h2>
        <h3>Ano do Veiculo: 2018</h3>
        <li>Valor: R$ 78.900,00</li>
        """
        with patch("integracoes.veiculos.scrapers.request") as mock_req:
            mock_req.return_value = MagicMock(status_code=200, text=html)
            itens = sc.coletar_007_batidos()
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["preco"], 78900.0)

    def test_coletar_fonte_veiculosbatidos_usa_leopardo(self):
        with patch.object(sc, "coletar_leopardo", return_value=[{"hash": "1"}]) as mock_leo:
            out = sc.coletar_fonte(
                {
                    "id": "veiculosbatidos",
                    "tipo": "leopardo",
                    "url_listagem": "https://www.veiculosbatidos.com.br/veiculos",
                    "ajax_url": "https://www.veiculosbatidos.com.br/loadveiculos",
                }
            )
        self.assertEqual(out, [{"hash": "1"}])
        mock_leo.assert_called_once()

    def test_parse_leopardo_url_protocol_relative(self):
        html = """
        <div class="col-list-3 divlinkclicable " id='divveiculo9673' data-identity='9673'>
        <h6 class='titulo-veiculo-card'><a href="//www.veiculosbatidos.com.br/veiculo/uno/9673">FIAT UNO</a></h6>
        <span class='pull-left text-bold'>2012/2013</span>
        <span class="price">R$ 15.000,00</span>
        </div></div></div></div>
        """
        itens = sc._parse_leopardo_html(
            html,
            {
                "id": "veiculosbatidos",
                "nome": "Veículos Batidos",
                "url_listagem": "https://www.veiculosbatidos.com.br/veiculos",
            },
        )
        self.assertEqual(len(itens), 1)
        self.assertTrue(itens[0]["url"].startswith("https://www.veiculosbatidos.com.br/"))

    def test_extrair_csrf_sem_aspas_no_name(self):
        html = '<meta name=csrf-token content="abc123">'
        self.assertEqual(sc._extrair_csrf(html), "abc123")


if __name__ == "__main__":
    unittest.main()
