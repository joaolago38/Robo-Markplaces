"""
tests/test_veiculos_scrapers.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.veiculos import scrapers as sc


class VeiculosScrapersTests(unittest.TestCase):
    def test_parse_preco_brl(self):
        self.assertEqual(sc.parse_preco_brl("R$ 13.500,00"), 13500.0)
        self.assertIsNone(sc.parse_preco_brl("Vendido"))
        self.assertIsNone(sc.parse_preco_brl("PRÉ-LIBERAÇÃO"))

    def test_parse_lucineia_html(self):
        html = """
        <a href="Veiculo.aspx?id=123"><img /></a>
        <h5 class="card-text alert-link">Uno Mille 1.0</h5>
        <p><small>Marca: Fiat<br />Ano: 2011 / 2012 <br /></small></p>
        <h5 class="card-text alert-link text-right">R$ 13.500,00</h5>
        """
        itens = sc._parse_leopardo_html(html, {"id": "x", "nome": "Teste"})
        self.assertEqual(len(itens), 0)
        for match in sc._RE_LUCINEIA_CARD.finditer(html):
            vid, titulo, marca, ano, preco_txt = match.groups()
            self.assertEqual(vid, "123")
            self.assertEqual(sc.parse_preco_brl(preco_txt), 13500.0)

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


if __name__ == "__main__":
    unittest.main()
