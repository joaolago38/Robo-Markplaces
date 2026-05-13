"""
tests/test_meta_ads_client.py — MA01–MA05
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.meta import meta_ads_client


def _mock_resp(body: dict) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    return r


class TestMetaAdsListar(unittest.TestCase):
    @patch.object(meta_ads_client, "META_AD_ACCOUNT_ID", "act_123")
    @patch.object(meta_ads_client, "META_ACCESS_TOKEN", "tok")
    @patch.object(meta_ads_client, "request")
    def test_MA01_listar_metricas_raw(self, mock_request, *_patches):
        mock_request.return_value = _mock_resp(
            {
                "data": [
                    {
                        "campaign_id": "c1",
                        "campaign_name": "Impala Manicures",
                        "spend": "100",
                        "cpc": "1.2",
                        "ctr": "1.5",
                    }
                ]
            }
        )
        metricas = meta_ads_client.listar_metricas_campanhas()
        self.assertEqual(metricas[0]["campaign_id"], "c1")
        self.assertEqual(metricas[0]["cpc"], "1.2")

    @patch.object(meta_ads_client, "META_ACCESS_TOKEN", "")
    @patch.object(meta_ads_client, "META_AD_ACCOUNT_ID", "act_x")
    def test_MA02_listar_metricas_token_vazio(self, *_patches):
        self.assertEqual(meta_ads_client.listar_metricas_campanhas(), [])

    @patch.object(meta_ads_client, "META_AD_ACCOUNT_ID", "act_123")
    @patch.object(meta_ads_client, "META_ACCESS_TOKEN", "tok")
    @patch.object(meta_ads_client, "request", side_effect=Exception("boom"))
    def test_MA03_listar_metricas_excecao(self, *_patches):
        self.assertEqual(meta_ads_client.listar_metricas_campanhas(), [])


class TestMetaAdsNormalizar(unittest.TestCase):
    def test_MA04_normalizar_converte_gasto_float(self):
        raw = {
            "campaign_id": "1",
            "spend": "100.5",
            "cpc": "1.20",
            "ctr": "2.0",
            "frequency": "3.5",
            "actions": [],
            "action_values": [],
        }
        norm = meta_ads_client.normalizar_metrica_campanha(raw)
        self.assertIsInstance(norm["gasto"], float)
        self.assertEqual(norm["gasto"], 100.5)

    def test_MA05_normalizar_roas_compras(self):
        raw = {
            "campaign_id": "1",
            "spend": "100.0",
            "cpc": "1",
            "ctr": "1",
            "frequency": "1",
            "actions": [],
            "action_values": [{"action_type": "purchase", "value": "350.0"}],
        }
        norm = meta_ads_client.normalizar_metrica_campanha(raw)
        self.assertEqual(norm.get("roas"), 3.5)


if __name__ == "__main__":
    unittest.main()
