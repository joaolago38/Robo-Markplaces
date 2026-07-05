"""
tests/test_sumare_leiloes.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.leilao import sumare_leiloes as sl


def _fake_sess_com_request(get_fn=None, post_fn=None):
    """Compatível com _request_sumare (sess.request) nos testes."""

    class FakeSess:
        headers = {}

        def get(self, url, timeout=30):
            if get_fn:
                return get_fn(url, timeout)
            raise AssertionError("get não mockado")

        def post(self, url, data=None, timeout=30, headers=None):
            if post_fn:
                return post_fn(url, data=data, timeout=timeout, headers=headers)
            raise AssertionError("post não mockado")

        def request(self, method, url, timeout=None, **kwargs):
            if method.upper() == "GET":
                return self.get(url, timeout=timeout or 30)
            if method.upper() == "POST":
                return self.post(
                    url,
                    data=kwargs.get("data"),
                    timeout=timeout or 30,
                    headers=kwargs.get("headers"),
                )
            raise AssertionError(f"método não mockado: {method}")

    return FakeSess()

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

    def test_enriquecer_lance_lote_html(self):
        lote = {"url": "https://www.sumareleiloes.com.br/lotes/x", "titulo": "FIAT/UNO"}
        html = """
        <table>
        <tr><td>Lance Inicial:</td><td>R$ 5.500,00</td></tr>
        <tr><td>Lance Atual:</td><td>R$ 6.200,00</td></tr>
        </table>
        COM DIREITO A DOCUMENTO/CIRCULAÇÃO
        """
        class FakeResp:
            status_code = 200
            text = html

        out = sl.enriquecer_lance_lote(lote, _fake_sess_com_request(get_fn=lambda url, timeout: FakeResp()))
        self.assertEqual(out["lance_brl"], 6200.0)
        self.assertTrue(out["tem_documento"])

    def test_varredura_sumare_mock(self):
        leilao = {"leilao_id": "5075", "comitente": "PREFEITURA X", "tipo_comitente": "prefeitura", "url": "http://x"}
        lote = sl._parse_lote_card(_LOTE_DOC, leilao=leilao)
        with patch.object(sl, "listar_leiloes_home", return_value=[leilao]):
            with patch.object(sl, "buscar_leiloes_detran_ddg", return_value=[]):
                with patch.object(sl, "coletar_lotes_leilao", return_value=[lote]):
                    with patch.object(sl, "enriquecer_lance_lote", side_effect=lambda lote, _sess: lote):
                        out = sl.varredura_sumare(
                            {"comitentes": ["prefeitura"], "lance_minimo_brl": 2000},
                            pausa_entre_leiloes_seg=0,
                            enriquecer_lances=False,
                        )
        self.assertEqual(out["leiloes_encontrados"], 1)
        self.assertEqual(out["leiloes_coletados_ok"], 1)
        self.assertEqual(out["lotes_veiculo_documento"], 1)

    def test_coletar_lotes_leilao_falha_rede_retorna_none(self):
        leilao = {"leilao_id": "3723", "url": "https://www.sumareleiloes.com.br/leiloes/3723"}
        with patch.object(sl, "_request_sumare", return_value=None):
            out = sl.coletar_lotes_leilao(leilao, sl._criar_sessao(), pausa_paginas_seg=0)
        self.assertIsNone(out)

    def test_listar_leiloes_home_mock(self):
        html = """
        <div class="auction-item">
            <div class="card-img-overlay-top">
                <div class="card-title">PREFEITURA DE TESTE</div>
            </div>
            <a href="https://www.sumareleiloes.com.br/leiloes/5075" class="goToAuction">Ver</a>
        </div>
        """
        class FakeResp:
            status_code = 200
            text = html

        leiloes = sl.listar_leiloes_home(_fake_sess_com_request(get_fn=lambda url, timeout: FakeResp()))
        self.assertEqual(len(leiloes), 1)
        self.assertEqual(leiloes[0]["tipo_comitente"], "prefeitura")

    def test_buscar_leiloes_detran_ddg_mock(self):
        with patch.object(
            sl,
            "ddg_buscar",
            return_value=[{"url": "https://www.sumareleiloes.com.br/leiloes/9999", "titulo": "DETRAN SP"}],
        ):
            leiloes = sl.buscar_leiloes_detran_ddg(max_resultados=5)
        self.assertEqual(len(leiloes), 1)
        self.assertEqual(leiloes[0]["tipo_comitente"], "detran")

    def test_parse_preco_invalido(self):
        self.assertIsNone(sl.parse_preco_brl(""))
        self.assertIsNone(sl.parse_preco_brl("sem preco"))

    def test_coletar_lotes_leilao_com_paginacao(self):
        leilao = {"leilao_id": "5075", "url": "https://www.sumareleiloes.com.br/leiloes/5075", "comitente": "PREFEITURA"}
        html_pag1 = f"var listaLotsTotal = 2; {_LOTE_DOC}"
        html_pag2 = _LOTE_SUCATA

        class FakeResp:
            def __init__(self, text, status_code=200):
                self.text = text
                self.status_code = status_code

        lotes = sl.coletar_lotes_leilao(
            leilao,
            _fake_sess_com_request(
                get_fn=lambda url, timeout: FakeResp(html_pag1),
                post_fn=lambda url, data=None, timeout=30, headers=None: FakeResp(html_pag2),
            ),
            pausa_paginas_seg=0,
        )
        self.assertEqual(len(lotes), 2)

    def test_eh_veiculo_blindado_rejeitado(self):
        lote = {"titulo": "FIAT/UNO BLINDADO", "tem_documento": True}
        self.assertFalse(sl.eh_veiculo_com_documento(lote))


if __name__ == "__main__":
    unittest.main()
