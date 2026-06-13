"""
tests/test_meta_ads_extra.py
Cobre as novas funções do meta_ads_client: período custom, paginação,
breakdown por plataforma, agregação e validação de conexão.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.meta import meta_ads_client as mac


def _resp(body: dict) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    return r


class TestPeriodoParams(unittest.TestCase):
    def test_preset_today(self):
        self.assertEqual(mac._periodo_params(1), {"date_preset": "today"})

    def test_preset_7d(self):
        self.assertEqual(mac._periodo_params(5), {"date_preset": "last_7d"})

    def test_preset_30d(self):
        self.assertEqual(mac._periodo_params(20), {"date_preset": "last_30d"})

    def test_intervalo_custom_tem_prioridade(self):
        p = mac._periodo_params(1, "2026-01-01", "2026-01-31")
        self.assertIn("time_range", p)
        self.assertIn("2026-01-01", p["time_range"])
        self.assertIn("2026-01-31", p["time_range"])


class TestListarComPaginacao(unittest.TestCase):
    @patch.object(mac, "META_AD_ACCOUNT_ID", "act_123")
    @patch.object(mac, "META_ACCESS_TOKEN", "tok")
    @patch.object(mac, "request")
    def test_segue_paginacao(self, mock_request, *_):
        pagina1 = _resp({"data": [{"campaign_id": "c1"}], "paging": {"next": "URL2"}})
        pagina2 = _resp({"data": [{"campaign_id": "c2"}]})
        mock_request.side_effect = [pagina1, pagina2]

        out = mac.listar_metricas_campanhas(periodo_dias=1)
        self.assertEqual([r["campaign_id"] for r in out], ["c1", "c2"])
        self.assertEqual(mock_request.call_count, 2)

    @patch.object(mac, "META_AD_ACCOUNT_ID", "act_123")
    @patch.object(mac, "META_ACCESS_TOKEN", "tok")
    @patch.object(mac, "request")
    def test_datas_custom_usa_time_range(self, mock_request, *_):
        mock_request.return_value = _resp({"data": []})
        mac.listar_metricas_campanhas(data_inicio="2026-01-01", data_fim="2026-01-31")
        _, kwargs = mock_request.call_args
        self.assertIn("time_range", kwargs["params"])

    @patch.object(mac, "META_ACCESS_TOKEN", "")
    @patch.object(mac, "META_AD_ACCOUNT_ID", "")
    def test_desabilitado_retorna_vazio(self, *_):
        self.assertEqual(mac.listar_metricas_campanhas(), [])

    @patch.object(mac, "META_AD_ACCOUNT_ID", "act_123")
    @patch.object(mac, "META_ACCESS_TOKEN", "tok")
    @patch.object(mac, "request", side_effect=Exception("boom"))
    def test_excecao_retorna_vazio(self, *_):
        self.assertEqual(mac.listar_metricas_campanhas(), [])


class TestPlataforma(unittest.TestCase):
    @patch.object(mac, "META_AD_ACCOUNT_ID", "act_123")
    @patch.object(mac, "META_ACCESS_TOKEN", "tok")
    @patch.object(mac, "request")
    def test_listar_por_plataforma_passa_breakdown(self, mock_request, *_):
        mock_request.return_value = _resp({"data": [{"publisher_platform": "instagram"}]})
        out = mac.listar_metricas_por_plataforma(periodo_dias=1)
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["params"]["breakdowns"], "publisher_platform")
        self.assertEqual(out[0]["publisher_platform"], "instagram")

    @patch.object(mac, "META_ACCESS_TOKEN", "")
    @patch.object(mac, "META_AD_ACCOUNT_ID", "")
    def test_listar_por_plataforma_desabilitado(self, *_):
        self.assertEqual(mac.listar_metricas_por_plataforma(), [])

    @patch.object(mac, "META_AD_ACCOUNT_ID", "act_123")
    @patch.object(mac, "META_ACCESS_TOKEN", "tok")
    @patch.object(mac, "request", side_effect=Exception("boom"))
    def test_listar_por_plataforma_excecao(self, *_):
        self.assertEqual(mac.listar_metricas_por_plataforma(), [])

    def test_normalizar_por_plataforma_agrega(self):
        rows = [
            {
                "publisher_platform": "instagram",
                "spend": "100",
                "impressions": "1000",
                "actions": [{"action_type": "purchase", "value": "2"}],
                "action_values": [{"action_type": "purchase", "value": "300"}],
            },
            {
                "publisher_platform": "instagram",
                "spend": "100",
                "impressions": "500",
                "actions": [],
                "action_values": [],
            },
            {
                "publisher_platform": "facebook",
                "spend": "50",
                "impressions": "200",
                "actions": [],
                "action_values": [{"action_type": "purchase", "value": "50"}],
            },
        ]
        out = mac.normalizar_por_plataforma(rows)
        self.assertEqual(out["instagram"]["gasto"], 200.0)
        self.assertEqual(out["instagram"]["receita"], 300.0)
        self.assertEqual(out["instagram"]["impressoes"], 1500)
        self.assertEqual(out["instagram"]["campanhas"], 2)
        self.assertEqual(out["instagram"]["roas"], 1.5)
        self.assertEqual(out["facebook"]["roas"], 1.0)

    def test_normalizar_por_plataforma_sem_gasto_roas_zero(self):
        rows = [{"publisher_platform": "instagram", "spend": "0", "actions": [], "action_values": []}]
        out = mac.normalizar_por_plataforma(rows)
        self.assertEqual(out["instagram"]["roas"], 0.0)

    def test_normalizar_por_plataforma_sem_chave_usa_desconhecida(self):
        out = mac.normalizar_por_plataforma([{"spend": "10", "actions": [], "action_values": []}])
        self.assertIn("desconhecida", out)


class TestNormalizarCampanha(unittest.TestCase):
    def test_impressoes_convertidas(self):
        norm = mac.normalizar_metrica_campanha(
            {"campaign_id": "1", "spend": "10", "impressions": "1234", "actions": [], "action_values": []}
        )
        self.assertEqual(norm["impressoes"], 1234)

    def test_to_float_invalido(self):
        self.assertEqual(mac._to_float("abc", 9.0), 9.0)


class TestValidarConexao(unittest.TestCase):
    @patch.object(mac, "META_ACCESS_TOKEN", "")
    def test_sem_token(self, *_):
        self.assertFalse(mac.validar_conexao()["ok"])

    @patch.object(mac, "META_ACCESS_TOKEN", "tok")
    @patch.object(mac, "META_AD_ACCOUNT_ID", "")
    def test_sem_conta(self, *_):
        out = mac.validar_conexao()
        self.assertFalse(out["ok"])
        self.assertIn("AD_ACCOUNT", out["erro"])

    @patch.object(mac, "META_AD_ACCOUNT_ID", "act_123")
    @patch.object(mac, "META_ACCESS_TOKEN", "tok")
    @patch.object(mac, "request")
    def test_ok(self, mock_request, *_):
        mock_request.side_effect = [
            _resp({"id": "1", "name": "Maria"}),
            _resp({"name": "Conta X", "currency": "BRL", "account_status": 1}),
        ]
        out = mac.validar_conexao()
        self.assertTrue(out["ok"])
        self.assertEqual(out["usuario"], "Maria")
        self.assertEqual(out["conta"], "Conta X")
        self.assertEqual(out["moeda"], "BRL")

    @patch.object(mac, "META_AD_ACCOUNT_ID", "act_123")
    @patch.object(mac, "META_ACCESS_TOKEN", "tok")
    @patch.object(mac, "request", side_effect=Exception("401"))
    def test_erro(self, *_):
        out = mac.validar_conexao()
        self.assertFalse(out["ok"])
        self.assertIn("401", out["erro"])


if __name__ == "__main__":
    unittest.main()
