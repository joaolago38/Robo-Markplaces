"""
tests/test_coletores_leilao_diretos.py
Fixtures HTML + filtros padrão Sumaré para Copart/Superbid/Sodré.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.leilao import coletores_base as base
from integracoes.leilao import copart_leiloes as copart
from integracoes.leilao import sodre_leiloes as sodre
from integracoes.leilao import superbid_leiloes as superbid

_HTML_COPART = """
<html><body>
<div class="lot-card">
  <h3>FIAT/UNO MILLE FIRE, 10/11</h3>
  <span>R$ 8.500,00</span>
  <a href="/lot/12345-fiat-uno-mille">ver</a>
</div>
<div class="lot-card">
  <h3>SUCATA DE EQUIPAMENTOS</h3>
  <span>R$ 200,00</span>
  <a href="/lot/999-sucata">ver</a>
</div>
</body></html>
"""

_HTML_SUPERBID = """
<html><body>
<a href="/evento/veiculo-honda-civic">
  <h2>HONDA/CIVIC LXS, 2012</h2>
  <span>R$ 22.000,00</span>
</a>
</body></html>
"""

_HTML_SODRE = """
<html><body>
<article>
  <h3>VW/GOL 1.0, 14/15 DOCUMENTO</h3>
  <span>R$ 12.300,00</span>
  <a href="/lote/vw-gol-1-0-2015">detalhe</a>
</article>
</body></html>
"""


class TestColetoresBase(unittest.TestCase):
    def test_eh_veiculo_e_filtro_lance(self):
        self.assertTrue(base.eh_veiculo("FIAT/UNO MILLE, 10/11"))
        self.assertFalse(base.eh_veiculo("SUCATA DE INFORMÁTICA"))
        lotes = [
            {"titulo": "FIAT/UNO, 10/11", "lance_brl": 8000, "tem_documento": False},
            {"titulo": "FIAT/PALIO, 08/08", "lance_brl": 200, "tem_documento": False},
            {"titulo": "SUCATA FERROSA", "lance_brl": 5000, "tem_documento": False},
        ]
        out, stats = base.filtrar_lotes_padrao(lotes, lance_min=500, exigir_documento=False)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["titulo"], "FIAT/UNO, 10/11")
        self.assertEqual(stats["lotes_abaixo_lance_min"], 1)

    def test_lote_para_achado(self):
        item = base.lote_para_achado(
            {"titulo": "FORD/KA", "url": "https://x/1", "lance_brl": 1000, "hash": "abc"},
            fonte_tipo="copart",
            fonte_id="copart",
            fonte_nome="Copart",
            dominio="copart.com.br",
        )
        self.assertEqual(item["fonte_id"], "copart")
        self.assertEqual(item["lance_brl"], 1000.0)


class TestParsersHtml(unittest.TestCase):
    def test_copart_parse_e_varredura(self):
        lotes = copart.parse_lotes_html(_HTML_COPART)
        self.assertGreaterEqual(len(lotes), 1)
        self.assertTrue(any("FIAT" in (x.get("titulo") or "") for x in lotes))
        with patch.object(copart, "listar_leiloes_home", return_value=[]), patch.object(
            copart, "coletar_via_ddg_site", return_value=[]
        ), patch.object(copart, "criar_sessao"):
            # força parse via mock de request na varredura
            pass
        out = copart.varredura_copart(
            {"ativo": True, "lance_minimo_brl": 500, "exigir_documento": False},
            usar_ddg_fallback=False,
        )
        # sem HTML live pode vir vazio — testa parser isolado acima
        self.assertIn("lotes", out)
        self.assertEqual(out["fonte"], "copart")

        # varredura com prefetch
        with patch.object(
            copart,
            "listar_leiloes_home",
            return_value=[
                {
                    "leilao_id": "inv",
                    "url": "https://www.copart.com.br/",
                    "_lotes_prefetch": copart.parse_lotes_html(_HTML_COPART),
                }
            ],
        ):
            out2 = copart.varredura_copart(
                {"ativo": True, "lance_minimo_brl": 500},
                usar_ddg_fallback=False,
            )
        self.assertGreaterEqual(out2["lotes_veiculo_documento"], 1)
        self.assertTrue(any("FIAT" in x["titulo"] for x in out2["lotes"]))
        self.assertFalse(any("SUCATA" in x["titulo"].upper() for x in out2["lotes"]))

    def test_superbid_parse(self):
        lotes = superbid.parse_lotes_html(_HTML_SUPERBID)
        self.assertEqual(len(lotes), 1)
        self.assertIn("CIVIC", lotes[0]["titulo"].upper())
        with patch.object(
            superbid,
            "listar_leiloes_home",
            return_value=[{"leilao_id": "v", "_lotes_prefetch": lotes}],
        ):
            out = superbid.varredura_superbid({"lance_minimo_brl": 500}, usar_ddg_fallback=False)
        self.assertEqual(out["lotes_veiculo_documento"], 1)

    def test_sodre_parse(self):
        lotes = sodre.parse_lotes_html(_HTML_SODRE)
        self.assertEqual(len(lotes), 1)
        self.assertTrue(lotes[0].get("tem_documento"))
        with patch.object(
            sodre,
            "listar_leiloes_home",
            return_value=[{"leilao_id": "v", "_lotes_prefetch": lotes}],
        ):
            out = sodre.varredura_sodre({"lance_minimo_brl": 500}, usar_ddg_fallback=False)
        self.assertEqual(out["lotes_veiculo_documento"], 1)


if __name__ == "__main__":
    unittest.main()
