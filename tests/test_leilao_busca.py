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

    def test_monta_termo_ano_padrao_2000_2020(self):
        termo = busca.montar_termo_busca({"marca": "Volkswagen", "modelo": "Gol"})
        self.assertIn("2000-2020", termo)

    def test_rejeita_ano_fora_do_intervalo_padrao(self):
        ok = busca._relevante_para_veiculo(
            {"titulo": "Volkswagen Gol 1998 leilão recuperado furto", "snippet": "lote veículo", "url": "http://x"},
            {"marca": "Volkswagen", "modelo": "Gol", "perfil": "recuperado_furto_pequena_monta"},
        )
        self.assertFalse(ok)

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
    def test_aceita_apenas_pequena_monta(self):
        blob = "Volkswagen Gol leilão pequena monta"
        self.assertTrue(busca._bate_perfil_recuperado_minimo(blob))

    def test_aceita_recuperado_media_monta(self):
        blob = "Fiat Fiorino leilão recuperado furto média monta DETRAN"
        self.assertTrue(busca._bate_perfil_recuperado_furto(blob))

    def test_rejeita_grande_monta(self):
        blob = "Gol leilão recuperado furto grande monta"
        self.assertFalse(busca._bate_perfil_recuperado_furto(blob))

    def test_relevante_exige_recuperado_nao_media_monta(self):
        ok = busca._relevante_para_veiculo(
            {
                "titulo": "Honda Civic leilão recuperado furto DETRAN",
                "snippet": "lote veículo",
                "url": "http://x/leilao",
            },
            {"marca": "Honda", "modelo": "Civic", "perfil": "recuperado_furto_media_monta"},
        )
        self.assertTrue(ok)

    def test_relevante_rejeita_sem_recuperado(self):
        ok = busca._relevante_para_veiculo(
            {"titulo": "Honda Civic leilão", "snippet": "lote normal", "url": "http://x"},
            {"marca": "Honda", "modelo": "Civic", "perfil": "recuperado_furto_media_monta"},
        )
        self.assertFalse(ok)

    def test_bate_perfil_minimo_sem_media_monta(self):
        blob = "Gol leilão recuperado furto DETRAN"
        self.assertTrue(busca._bate_perfil_recuperado_minimo(blob))
        self.assertFalse(busca._bate_perfil_recuperado_furto(blob))

    def test_rejeita_sem_furto_nem_monta(self):
        blob = "Gol leilão seminovo revisado"
        self.assertFalse(busca._bate_perfil_recuperado_minimo(blob))

    def test_rotacionar_fontes(self):
        fontes = [{"id": str(i)} for i in range(10)]
        sel = busca._rotacionar_fontes(fontes, limite=3, bucket=2)
        self.assertEqual(len(sel), 3)
        self.assertEqual(sel[0]["id"], "2")

    def test_lote_sumare_para_item(self):
        lote = {
            "titulo": "VOLKSWAGEN/GOL 1.0, 14/15",
            "url": "https://www.sumareleiloes.com.br/lotes/abc",
            "hash": "h1",
            "lance_brl": 8500.0,
            "comitente": "DETRAN SP",
            "local_data": "Campinas / SP",
        }
        veiculo = {"marca": "Volkswagen", "modelo": "Gol", "perfil": "recuperado_furto_media_monta"}
        item = busca._lote_sumare_para_item(lote, veiculo)
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item["fonte_tipo"], "sumare")
        self.assertEqual(item["lance_brl"], 8500.0)

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
    @patch("core.ddg_lite.extrair_resultados_lite")
    @patch("core.ddg_lite._ddg_request")
    def test_retry_403_depois_ok(self, mock_request, mock_extrair, _sleep):
        from core.ddg_lite import reset_circuit_breaker

        reset_circuit_breaker()
        mock_extrair.return_value = [{"titulo": "x", "url": "http://a", "snippet": ""}]
        ok = MagicMock()
        ok.status_code = 200
        ok.text = "<html></html>"
        bloqueado = MagicMock()
        bloqueado.status_code = 403
        bloqueado.text = ""
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
            "dominio": "copart.com.br",
            "url": "https://www.copart.com.br/lote/1",
        }
        out = busca.enriquecer_achado_leilao(item, {"marca": "Volkswagen", "modelo": "Gol"})
        self.assertEqual(out["ano"], 2014)
        self.assertEqual(out["valor"], "R$ 12.000")
        self.assertIn("copart.com.br", out.get("url_cadastro", ""))

    def test_extrai_data_e_url_cadastro_do_snippet(self):
        item = {
            "titulo": "Honda Civic leilão dia 15/07/2026",
            "snippet": "inscrição em https://www.detran.pr.gov.br/cadastro-leilao",
            "fonte_tipo": "detran",
            "fonte_id": "PR",
            "fonte_nome": "DETRAN Paraná",
            "dominio": "detran.pr.gov.br",
            "url": "https://www.detran.pr.gov.br/edital/1",
        }
        out = busca.enriquecer_achado_leilao(item, {"marca": "Honda", "modelo": "Civic"})
        self.assertEqual(out["data_leilao"], "15/07/2026")
        self.assertIn("cadastro-leilao", out["url_cadastro"])


class TestFontesCadastro(unittest.TestCase):
    def test_tem_27_detran(self):
        ufs = {f["uf"] for f in DETRAN_POR_ESTADO}
        self.assertEqual(len(ufs), 27)

    def test_leiloeiros_principais(self):
        self.assertGreaterEqual(len(LEILOEIROS_PRINCIPAIS), 10)


class TestBuscarVeiculo(unittest.TestCase):
    @patch.object(busca, "obter_lotes_sumare", return_value=([], {"lotes_veiculo": 0}))
    @patch.object(busca, "_fontes_da_rodada")
    @patch.object(busca, "buscar_duckduckgo", return_value=[
        {
            "titulo": "Fiat Uno 2012 leilão recuperado furto DETRAN",
            "url": "https://www.copart.com.br/lote/123",
            "snippet": "veículo recuperado furto",
        }
    ])
    @patch.object(busca.time, "sleep")
    def test_deduplica_e_filtra(self, _sleep, _ddg, mock_fontes, _sumare):
        mock_fontes.return_value = (
            [({"dominio": "copart.com.br", "nome": "Copart", "id": "copart"}, "leiloeiro", "copart")],
            {"leiloeiros_na_rodada": 1, "detrans_na_rodada": 0},
        )
        veiculo = {
            "marca": "Fiat",
            "modelo": "Uno",
            "ano_min": 2010,
            "ano_max": 2015,
            "perfil": "recuperado_furto_media_monta",
        }
        out = busca.buscar_veiculo_em_fontes(
            veiculo,
            incluir_detran=False,
            pausa_entre_fontes_seg=0,
            lotes_sumare=[],
        )
        achados = out["achados"]
        self.assertTrue(any("copart.com.br" in a.get("url", "") for a in achados))
        self.assertIn("diagnostico", out)
        self.assertGreaterEqual(out["diagnostico"].get("ddg_brutos", 0), 1)


if __name__ == "__main__":
    unittest.main()
