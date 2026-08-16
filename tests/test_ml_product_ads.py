"""
tests/test_ml_product_ads.py
Testes mockados do controle real de Product Ads no Mercado Livre.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import integracoes.ml.ml_product_ads as ads


def _resp(body: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.content = b"{}"
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status}")
    r.json.return_value = body
    return r


class TestObterAdvertiser(unittest.TestCase):
    @patch.object(ads, "_enabled", return_value=False)
    def test_desabilitado(self, *_):
        self.assertFalse(ads.obter_advertiser()["ok"])

    @patch.object(ads, "_request_ml")
    @patch.object(ads, "_enabled", return_value=True)
    def test_ok(self, _en, mock_req):
        mock_req.return_value = _resp({"advertisers": [{"advertiser_id": "123", "site_id": "MLB"}]})
        out = ads.obter_advertiser()
        self.assertTrue(out["ok"])
        self.assertEqual(out["advertiser_id"], "123")

    @patch.object(ads, "_request_ml")
    @patch.object(ads, "_enabled", return_value=True)
    def test_sem_permissao_404(self, _en, mock_req):
        mock_req.return_value = _resp({"message": "No permissions found for user_id"}, status=404)
        out = ads.obter_advertiser()
        self.assertFalse(out["ok"])
        self.assertEqual(out.get("codigo"), "sem_permissao")


class TestListarCampanhas(unittest.TestCase):
    @patch.object(ads, "obter_advertiser", return_value={"ok": True, "advertiser_id": "A1"})
    @patch.object(ads, "_request_ml")
    @patch.object(ads, "_enabled", return_value=True)
    def test_lista_normalizada(self, _en, mock_req, *_):
        mock_req.return_value = _resp({
            "results": [
                {
                    "id": "C1",
                    "name": "Camp Impala",
                    "status": "active",
                    "budget": 50,
                    "metrics": {
                        "acos": 0.15,
                        "cost": 100,
                        "roas": 4.0,
                        "clicks": 10,
                        "prints": 500,
                        "ctr": 2.0,
                        "cvr": 0.04,
                        "cpc": 1.2,
                    },
                }
            ]
        })
        out = ads.listar_campanhas()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "C1")
        self.assertEqual(out[0]["acos"], 0.15)
        self.assertEqual(out[0]["prints"], 500)
        self.assertEqual(out[0]["ctr"], 2.0)
        self.assertEqual(out[0]["cvr"], 0.04)

    @patch.object(ads, "obter_advertiser", return_value={"ok": True, "advertiser_id": "421764"})
    @patch.object(ads, "_request_ml")
    @patch.object(ads, "_enabled", return_value=True)
    def test_lista_404_vira_warning_nao_error(self, _en, mock_req, *_):
        err = Exception("404 Client Error: Not Found")
        err.response = MagicMock(status_code=404)
        mock_req.side_effect = err
        ads._ULTIMO_AVISO_404_TS = 0.0
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ads, "_COOLDOWN_404_PATH", Path(tmp) / "ads_404.json"):
                with self.assertLogs("ml_product_ads", level="WARNING") as cm:
                    out = ads.listar_campanhas(advertiser_id="421764")
        self.assertEqual(out, [])
        self.assertEqual(ads.ultima_listagem_codigo(), "http_404")
        self.assertTrue(any("HTTP 404" in m for m in cm.output))
        self.assertFalse(any("ERROR:" in m for m in cm.output))

    @patch.object(ads, "obter_advertiser", return_value={"ok": True, "advertiser_id": "421764"})
    @patch.object(ads, "_request_ml")
    @patch.object(ads, "_enabled", return_value=True)
    def test_lista_404_suprimido_em_cooldown(self, _en, mock_req, *_):
        err = Exception("404 Client Error: Not Found")
        err.response = MagicMock(status_code=404)
        mock_req.side_effect = err
        ads._ULTIMO_AVISO_404_TS = 0.0
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ads_404.json"
            with patch.object(ads, "_COOLDOWN_404_PATH", path):
                with self.assertLogs("ml_product_ads", level="WARNING") as cm1:
                    ads.listar_campanhas(advertiser_id="421764")
                self.assertEqual(len(cm1.output), 1)
                ads._ULTIMO_AVISO_404_TS = 0.0
                with self.assertRaises(AssertionError):
                    with self.assertLogs("ml_product_ads", level="WARNING"):
                        ads.listar_campanhas(advertiser_id="421764")


class TestProbeEscrita404(unittest.TestCase):
    @patch.object(ads, "listar_campanhas", return_value=[])
    @patch.object(
        ads,
        "obter_advertiser",
        return_value={"ok": True, "advertiser_id": "421764", "site_id": "MLB"},
    )
    def test_probe_propaga_http_404(self, *_):
        ads._ULTIMA_LISTAGEM = {
            "ok": False,
            "codigo": "http_404",
            "advertiser_id": "421764",
        }
        out = ads.probe_escrita_product_ads()
        self.assertFalse(out["ok"])
        self.assertEqual(out["codigo"], "http_404")


class TestEscritaCampanha(unittest.TestCase):
    @patch.object(ads, "_enabled", return_value=True)
    @patch.object(ads, "ML_ADS_KILL_SWITCH", False)
    @patch.object(ads, "ML_ADS_ORCAMENTO_MAXIMO", 500.0)
    def test_pausar_dry_run(self, *_):
        out = ads.pausar_campanha("C1", "MLB", dry_run=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["dry_run"])

    @patch.object(ads, "ML_ADS_KILL_SWITCH", False)
    @patch.object(ads, "_request_ml")
    @patch.object(ads, "_enabled", return_value=True)
    def test_pausar_confirmado(self, _en, mock_req):
        mock_req.return_value = _resp({"status": "paused"})
        out = ads.pausar_campanha("C1", "MLB", dry_run=False, confirmar=True)
        self.assertTrue(out["ok"])
        self.assertFalse(out["dry_run"])

    @patch.object(ads, "ML_ADS_KILL_SWITCH", True)
    def test_kill_switch_bloqueia(self):
        out = ads.pausar_campanha("C1", "MLB", dry_run=False, confirmar=True)
        self.assertFalse(out["ok"])

    @patch.object(ads, "ML_ADS_KILL_SWITCH", False)
    @patch.object(ads, "ML_ADS_ORCAMENTO_MAXIMO", 100.0)
    def test_orcamento_acima_limite(self):
        out = ads.definir_orcamento("C1", 200.0, "MLB", dry_run=False, confirmar=True)
        self.assertFalse(out["ok"])

    def test_sem_confirmar(self):
        out = ads.ativar_campanha("C1", "MLB", dry_run=False, confirmar=False)
        self.assertFalse(out["ok"])


class TestAcosLimite(unittest.TestCase):
    @patch.object(ads, "listar_campanhas", return_value=[
        {"id": "C1", "acos": 0.30, "cost": 50},
        {"id": "C2", "acos": 0.10, "cost": 20},
    ])
    def test_filtra_acima(self, *_):
        out = ads.campanhas_acos_acima_limite(limite=0.20)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "C1")


class TestAplicarDecisao(unittest.TestCase):
    @patch.object(ads, "listar_campanhas", return_value=[{"id": "C1"}])
    @patch.object(ads, "obter_advertiser", return_value={"ok": True, "advertiser_id": "A1", "site_id": "MLB"})
    @patch.object(ads, "pausar_campanha", return_value={"ok": True, "dry_run": True})
    def test_aplicar_pausar(self, mock_pausar, *_):
        out = ads.aplicar_decisao_campanhas("pausar", dry_run=True)
        self.assertEqual(len(out), 1)
        mock_pausar.assert_called_once()

    @patch.object(ads, "listar_campanhas", return_value=[
        {"id": "C1"},
        {"id": "C2"},
        {"id": "C3"},
    ])
    @patch.object(ads, "obter_advertiser", return_value={"ok": True, "advertiser_id": "A1", "site_id": "MLB"})
    @patch.object(ads, "pausar_campanha", return_value={"ok": True, "dry_run": True})
    def test_aplicar_pausar_somente_ids_informados(self, mock_pausar, *_):
        out = ads.aplicar_decisao_campanhas("pausar", dry_run=True, campaign_ids=["C2"])
        self.assertEqual(len(out), 1)
        mock_pausar.assert_called_once_with("C2", "MLB", dry_run=True, confirmar=False)

    @patch.object(ads, "listar_campanhas", return_value=[{"id": "C1"}])
    @patch.object(ads, "obter_advertiser", return_value={"ok": True, "advertiser_id": "A1", "site_id": "MLB"})
    @patch.object(ads, "definir_orcamento", return_value={"ok": True, "dry_run": True})
    @patch.object(ads, "ativar_campanha", return_value={"ok": True, "dry_run": True})
    def test_aplicar_ligar_ativa_e_define_orcamento(self, mock_ativar, mock_orcamento, *_):
        out = ads.aplicar_decisao_campanhas("ligar", budget=10.0, dry_run=True)
        self.assertEqual(len(out), 2)
        mock_ativar.assert_called_once_with("C1", "MLB", dry_run=True, confirmar=False)
        mock_orcamento.assert_called_once_with("C1", 10.0, "MLB", dry_run=True, confirmar=False)

    @patch.object(ads, "listar_campanhas", return_value=[{"id": "C1"}])
    @patch.object(ads, "obter_advertiser", return_value={"ok": True, "advertiser_id": "A1", "site_id": "MLB"})
    @patch.object(ads, "definir_orcamento", return_value={"ok": True, "dry_run": True})
    @patch.object(ads, "ativar_campanha", return_value={"ok": True, "dry_run": True})
    def test_aplicar_ligar_sem_budget_so_ativa(self, mock_ativar, mock_orcamento, *_):
        out = ads.aplicar_decisao_campanhas("ativar", budget=0.0, dry_run=True)
        self.assertEqual(len(out), 1)
        mock_ativar.assert_called_once()
        mock_orcamento.assert_not_called()


class TestVisibilidadeCtrCvr(unittest.TestCase):
    def test_normalizar_guarda_ctr_cvr_prints(self):
        row = ads._normalizar_campanha(
            {
                "id": "C1",
                "metrics": {
                    "acos": 0.1,
                    "clicks": 8,
                    "prints": 400,
                    "ctr": 2.0,
                    "cvr": 0.05,
                    "cpc": 0.9,
                },
            }
        )
        self.assertEqual(row["prints"], 400)
        self.assertEqual(row["ctr"], 2.0)
        self.assertEqual(row["cvr"], 0.05)
        self.assertEqual(row["cpc"], 0.9)

    @patch("core.datadog_metrics.gauge")
    def test_emitir_visibilidade_sem_sku_tag(self, mock_gauge):
        ads.emitir_metricas_visibilidade_ads(
            [{"prints": 100, "clicks": 4, "ctr": 4.0, "cvr": 0.1, "cpc": 1.0}]
        )
        nomes = [c.args[0] for c in mock_gauge.call_args_list]
        self.assertIn("ads.ctr_medio", nomes)
        self.assertIn("ads.cvr_medio", nomes)
        self.assertIn("ads.ctr_cvr_visivel", nomes)
        for c in mock_gauge.call_args_list:
            self.assertNotIn("tags", c.kwargs)


if __name__ == "__main__":
    unittest.main()

