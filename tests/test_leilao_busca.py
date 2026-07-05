"""
tests/test_leilao_busca.py
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

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

    def test_termo_site_enxuto_sem_perfil_duplicado(self):
        veiculo = {
            "marca": "Volkswagen",
            "modelo": "Gol",
            "perfil": "recuperado_furto_media_monta",
        }
        completo = busca.montar_termo_busca(veiculo)
        site = busca._termo_query_site(veiculo)
        self.assertIn("recuperado", completo)
        self.assertNotIn("recuperado", site)
        self.assertIn("Gol", site)

    def test_monta_termo_com_perfil_recuperado(self):
        termo = busca.montar_termo_busca(
            {
                "marca": "Fiat",
                "modelo": "Fiorino",
                "perfil": "recuperado_furto_media_monta",
                "termos_extra": ["furgão"],
            }
        )
        self.assertIn("recuperado", termo)
        self.assertIn("média monta", termo)
        self.assertIn("furgão", termo)


class TestPerfilRecuperado(unittest.TestCase):
    def test_aceita_recuperado_media_monta(self):
        blob = "Fiat Fiorino leilão recuperado furto média monta DETRAN"
        self.assertTrue(busca._bate_perfil_recuperado_furto(blob))

    def test_rejeita_grande_monta(self):
        blob = "Gol leilão recuperado furto grande monta"
        self.assertFalse(busca._bate_perfil_recuperado_furto(blob))

    def test_relevante_exige_perfil(self):
        ok = busca._relevante_para_veiculo(
            {"titulo": "Honda Civic leilão", "snippet": "lote normal", "url": "http://x"},
            {"marca": "Honda", "modelo": "Civic", "perfil": "recuperado_furto_media_monta"},
        )
        self.assertFalse(ok)

    def test_relevante_civic_recuperado(self):
        ok = busca._relevante_para_veiculo(
            {
                "titulo": "Civic leilão recuperado furto média monta",
                "snippet": "DETRAN",
                "url": "http://x/leilao",
            },
            {"marca": "Honda", "modelo": "Civic", "perfil": "recuperado_furto_media_monta"},
        )
        self.assertTrue(ok)


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


class TestDdgRetry(unittest.TestCase):
    @patch("core.ddg_lite.time.sleep")
    @patch("core.ddg_lite.extrair_resultados")
    @patch("core.ddg_lite.request")
    def test_retry_403_depois_ok(self, mock_request, mock_extrair, _sleep):
        from core.ddg_lite import reset_circuit_breaker

        reset_circuit_breaker()
        mock_extrair.return_value = [{"titulo": "x", "url": "http://a", "snippet": ""}]
        ok = MagicMock()
        ok.status_code = 200
        ok.text = "<html></html>"
        bloqueado = MagicMock()
        bloqueado.status_code = 403
        mock_request.side_effect = [bloqueado, ok]
        out = busca.buscar_duckduckgo("teste")
        self.assertEqual(len(out), 1)
        self.assertEqual(mock_request.call_count, 2)


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


class TestEnriquecerAchado(unittest.TestCase):
    def test_extrai_cidade_detran_ano_valor(self):
        item = {
            "titulo": "Fiat Fiorino 2018 leilão Campinas/SP",
            "snippet": "veículo recuperado lance R$ 18.500,00",
            "fonte_tipo": "detran",
            "fonte_id": "SP",
            "fonte_nome": "DETRAN São Paulo",
        }
        veiculo = {"marca": "Fiat", "modelo": "Fiorino", "ano_min": 2015, "ano_max": 2020}
        out = busca.enriquecer_achado_leilao(item, veiculo)
        self.assertEqual(out["cidade"], "Campinas")
        self.assertEqual(out["uf"], "SP")
        self.assertEqual(out["detran_nome"], "DETRAN São Paulo")
        self.assertEqual(out["ano"], 2018)
        self.assertEqual(out["valor"], "R$ 18.500,00")
        self.assertEqual(out["marca"], "Fiat")
        self.assertEqual(out["modelo"], "Fiorino")

    def test_leiloeiro_sem_cidade_mostra_fonte(self):
        item = {
            "titulo": "Volkswagen Gol 2014 leilão",
            "snippet": "arremate R$ 12000",
            "fonte_tipo": "leiloeiro",
            "fonte_nome": "Copart Brasil",
        }
        out = busca.enriquecer_achado_leilao(item, {"marca": "Volkswagen", "modelo": "Gol"})
        self.assertEqual(out["ano"], 2014)
        self.assertEqual(out["valor"], "R$ 12.000")


class TestFontesCadastro(unittest.TestCase):
    def test_tem_27_detran(self):
        ufs = {f["uf"] for f in DETRAN_POR_ESTADO}
        self.assertEqual(len(ufs), 27)

    def test_leiloeiros_principais(self):
        self.assertGreaterEqual(len(LEILOEIROS_PRINCIPAIS), 10)


class TestBuscarVeiculo(unittest.TestCase):
    @patch.object(busca, "buscar_duckduckgo", return_value=[
        {
            "titulo": "Fiat Uno 2012 leilão recuperado furto média monta",
            "url": "https://www.copart.com.br/lote/123",
            "snippet": "veículo recuperado furto média monta",
        }
    ])
    @patch.object(busca.time, "sleep")
    def test_deduplica_e_filtra(self, _sleep, _ddg):
        veiculo = {
            "marca": "Fiat",
            "modelo": "Uno",
            "ano_min": 2010,
            "ano_max": 2015,
            "perfil": "recuperado_furto_media_monta",
        }
        achados = busca.buscar_veiculo_em_fontes(
            veiculo,
            incluir_detran=False,
            pausa_entre_fontes_seg=0,
        )
        self.assertTrue(any("copart.com.br" in a.get("url", "") for a in achados))


if __name__ == "__main__":
    unittest.main()
