"""
tests/test_leilao_busca.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.leilao import busca
from integracoes.leilao.fontes import DETRAN_POR_ESTADO, LEILOEIROS_PRINCIPAIS


class TestMontarTermo(unittest.TestCase):
    def test_monta_marca_modelo_ano(self):
        termo = busca.montar_termo_busca(
            {"marca": "Fiat", "modelo": "Uno", "ano_min": 2012, "ano_max": 2012}
        )
        self.assertIn("Fiat", termo)
        self.assertIn("Uno", termo)
        self.assertIn("2012", termo)


class TestExtrairDdg(unittest.TestCase):
    def test_parse_resultado(self):
        html = '''
        <div class="result results_links results_links_deep web-result">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fcopart.com.br%2Flote">Fiat Uno leilão</a>
          <a class="result__snippet">Veículo em leilão Copart</a>
        </div>
        '''
        itens = busca._extrair_resultados_ddg(html)
        self.assertEqual(len(itens), 1)
        self.assertIn("copart.com.br", itens[0]["url"])


class TestRelevancia(unittest.TestCase):
    def test_rejeita_sem_marca(self):
        ok = busca._relevante_para_veiculo(
            {"titulo": "Honda Civic leilão", "snippet": "", "url": "http://x"},
            {"marca": "Fiat", "modelo": "Uno"},
        )
        self.assertFalse(ok)

    def test_aceita_com_leilao(self):
        ok = busca._relevante_para_veiculo(
            {"titulo": "Fiat Uno 2012 leilão", "snippet": "lote veículo", "url": "http://x"},
            {"marca": "Fiat", "modelo": "Uno", "ano_min": 2010, "ano_max": 2015},
        )
        self.assertTrue(ok)


class TestFontesCadastro(unittest.TestCase):
    def test_tem_27_detran(self):
        ufs = {f["uf"] for f in DETRAN_POR_ESTADO}
        self.assertEqual(len(ufs), 27)

    def test_leiloeiros_principais(self):
        self.assertGreaterEqual(len(LEILOEIROS_PRINCIPAIS), 10)


class TestBuscarVeiculo(unittest.TestCase):
    @patch.object(busca, "buscar_duckduckgo", return_value=[
        {
            "titulo": "Fiat Uno 2012 leilão Copart",
            "url": "https://www.copart.com.br/lote/123",
            "snippet": "veículo em leilão",
        }
    ])
    @patch.object(busca.time, "sleep")
    def test_deduplica_e_filtra(self, _sleep, _ddg):
        veiculo = {"marca": "Fiat", "modelo": "Uno", "ano_min": 2010, "ano_max": 2015}
        achados = busca.buscar_veiculo_em_fontes(
            veiculo,
            incluir_detran=False,
            pausa_entre_fontes_seg=0,
        )
        self.assertTrue(any("copart.com.br" in a.get("url", "") for a in achados))


if __name__ == "__main__":
    unittest.main()
