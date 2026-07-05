"""
tests/test_sumare_leiloes.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.leilao import sumare_leiloes as sl

_LOTE_DOC = """
<div class="lot-item">
    <div class="card-title card-title-2lines">FIAT/UNO MILLE ECONOMY, 11/12</div>
    <span class="ellipsis font-smaller"><i class="fa fa-map-marker"></i> RIBEIRAO DO SUL / SP  - 15/07/2026</span><span>R$ 5.500,00</span>
    <div class="favorite-button " data-id="2460aa8a-b15d-475b-b6fb-f6e84590a7c5">
    <span class="font-bold">LOTE 0009</span>
    <span class="font-bolder ml-2">DOCUMENTO</span>
    <a href="https://www.sumareleiloes.com.br/lotes/2460aa8a-b15d-475b-b6fb-f6e84590a7c5">
</div></div></div>
"""

_LOTE_SUCATA = """
<div class="lot-item">
    <div class="card-title card-title-2lines">SUCATA DE EQUIPAMENTOS DE INFORMÁTICA</div>
    <span>R$ 700,00</span>
    <span class="font-bold">LOTE 0002</span>
    <a href="https://www.sumareleiloes.com.br/lotes/44e72576-ef8a-46bb-9ca5-729e5b783c48">
</div></div></div>
"""


class SumareLeiloesTests(unittest.TestCase):
    def test_parse_preco(self):
        self.assertEqual(sl.parse_preco_brl("R$ 5.500,00"), 5500.0)

    def test_eh_veiculo_com_documento(self):
        lote_doc = sl._parse_lote_card(_LOTE_DOC, leilao={"leilao_id": "5075", "comitente": "PREFEITURA"})
        self.assertIsNotNone(lote_doc)
        self.assertTrue(sl.eh_veiculo_com_documento(lote_doc))

        lote_suc = sl._parse_lote_card(_LOTE_SUCATA, leilao={"leilao_id": "5075"})
        self.assertIsNotNone(lote_suc)
        self.assertFalse(sl.eh_veiculo_com_documento(lote_suc))

    def test_classificar_comitente(self):
        self.assertEqual(sl._classificar_comitente("PREFEITURA - RIBEIRÃO DO SUL"), "prefeitura")
        self.assertEqual(sl._classificar_comitente("DETRAN SÃO PAULO"), "detran")

    def test_filtrar_leiloes(self):
        leiloes = [
            {"leilao_id": "1", "comitente": "PREFEITURA X", "tipo_comitente": "prefeitura"},
            {"leilao_id": "2", "comitente": "BANCO XYZ"},
        ]
        out = sl.filtrar_leiloes_por_comitente(leiloes, ["prefeitura", "detran"])
        self.assertEqual(len(out), 1)

    def test_extrair_lotes_html(self):
        leilao = {"leilao_id": "5075", "comitente": "PREFEITURA - RIBEIRÃO DO SUL", "tipo_comitente": "prefeitura"}
        lotes = sl._extrair_lotes_html(_LOTE_DOC + _LOTE_SUCATA, leilao)
        self.assertEqual(len(lotes), 2)


if __name__ == "__main__":
    unittest.main()
