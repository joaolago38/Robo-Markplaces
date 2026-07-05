"""
tests/test_veiculos_fipe_comparacao.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.veiculos import comparacao as cmp
from integracoes.veiculos import fipe_client as fipe


class FipeComparacaoTests(unittest.TestCase):
    def test_normalizar_e_aliases(self):
        self.assertEqual(fipe._normalizar("Citroën"), "citroen")
        self.assertEqual(fipe._ALIASES_MARCA["vw"], "Volkswagen")

    def test_parse_valor_fipe(self):
        self.assertEqual(fipe.parse_valor_fipe("R$ 32.500,00"), 32500.0)
        self.assertEqual(fipe.parse_valor_fipe(""), 0.0)

    def test_extrair_ano(self):
        self.assertEqual(fipe._extrair_ano("2011 / 2012"), 2011)
        self.assertIsNone(fipe._extrair_ano("sem ano"))

    def test_calcular_margem(self):
        m = cmp.calcular_margem_fipe(preco_anunciado=10000, valor_fipe=20000)
        self.assertEqual(m["desconto_pct"], 50.0)
        self.assertEqual(m["margem_reais"], 10000.0)

    def test_calcular_margem_fipe_zero(self):
        m = cmp.calcular_margem_fipe(preco_anunciado=10000, valor_fipe=0)
        self.assertEqual(m["desconto_pct"], 0.0)

    @patch("integracoes.veiculos.comparacao.consultar_preco_fipe")
    def test_avaliar_anuncio_oportunidade(self, mock_fipe):
        mock_fipe.return_value = {
            "valor_fipe": 20000.0,
            "marca_fipe": "Fiat",
            "modelo_fipe": "Uno",
            "ano_fipe": 2012,
        }
        anuncio = {
            "hash": "abc",
            "titulo": "Uno Mille",
            "marca": "Fiat",
            "ano": "2011/2012",
            "preco": 12000.0,
            "url": "http://x",
        }
        out = cmp.avaliar_anuncio(anuncio, preco_max=20000, margem_min_pct=25)
        self.assertTrue(out)
        self.assertGreaterEqual(out["desconto_pct"], 25)

    @patch("integracoes.veiculos.comparacao.consultar_preco_fipe")
    def test_avaliar_rejeita_margem_baixa(self, mock_fipe):
        mock_fipe.return_value = {"valor_fipe": 15000.0}
        out = cmp.avaliar_anuncio(
            {"preco": 14000, "marca": "Fiat", "titulo": "Uno", "ano": "2012"},
            preco_max=20000,
            margem_min_pct=25,
        )
        self.assertIsNone(out)

    @patch("integracoes.veiculos.comparacao.consultar_preco_fipe")
    def test_avaliar_rejeita_preco_alto(self, mock_fipe):
        out = cmp.avaliar_anuncio(
            {"preco": 25000, "marca": "X", "titulo": "Y", "ano": "2010"},
            preco_max=20000,
            margem_min_pct=10,
        )
        self.assertIsNone(out)
        mock_fipe.assert_not_called()

    @patch("integracoes.veiculos.comparacao.avaliar_anuncio")
    def test_filtrar_oportunidades(self, mock_avaliar):
        mock_avaliar.side_effect = [None, {"desconto_pct": 40, "titulo": "A"}, {"desconto_pct": 50, "titulo": "B"}]
        out = cmp.filtrar_oportunidades([{}, {}, {}], preco_max=20000, margem_min_pct=25)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["desconto_pct"], 50)

    @patch("integracoes.veiculos.fipe_client._get_json")
    def test_resolver_marca_e_consulta(self, mock_get):
        mock_get.side_effect = [
            [{"codigo": "21", "nome": "Fiat"}],
            {"modelos": [{"codigo": "1", "nome": "Uno Mille 1.0"}]},
            [{"codigo": "2012-1", "nome": "2012 Gasolina"}],
            {"Valor": "R$ 25.000,00", "AnoModelo": 2012, "Combustivel": "Gasolina", "CodigoFipe": "001"},
        ]
        out = fipe.consultar_preco_fipe(marca="Fiat", titulo="Uno Mille 1.0", ano_texto="2011/2012")
        self.assertIsNotNone(out)
        self.assertEqual(out["valor_fipe"], 25000.0)

    @patch("integracoes.veiculos.fipe_client.request")
    def test_get_json_erro_http(self, mock_req):
        mock_req.return_value = MagicMock(status_code=500)
        fipe._CACHE.clear()
        self.assertIsNone(fipe._get_json("carros/marcas"))

    def test_tokens_modelo(self):
        tokens = fipe._tokens_modelo("Gol 1.0 Total Flex 2012")
        self.assertIn("gol", tokens)


if __name__ == "__main__":
    unittest.main()
