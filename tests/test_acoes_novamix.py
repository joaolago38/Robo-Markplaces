"""
tests/test_acoes_novamix.py
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.ml import acoes_novamix as ac


class TestPlanoAcoesNovamix(unittest.TestCase):
    def test_guerra_sugere_pausar_ads(self):
        analise = {
            "ok": True,
            "nickname": "NOVAMIX_COMERCIAL",
            "ameacas_preco": [
                {
                    "sku": "IMP-BAIL-005",
                    "meu_preco": 48.9,
                    "menor_preco_loja": 30.99,
                    "gap_pct": 57.8,
                }
            ],
            "estrategia": {"porte": "gigante", "ameaca_geral": "alta"},
        }
        produtos = [
            {
                "sku": "IMP-BAIL-005",
                "custo": 20.0,
                "canais": {"mercadolivre": {"preco": 48.9}},
            }
        ]
        plano = ac.gerar_plano_acoes_novamix(analise, produtos=produtos, max_acoes=5)
        self.assertTrue(plano["ok"])
        self.assertEqual(plano["ads_sugerido"], "pausar")
        self.assertIn("IMP-BAIL-005", plano["caixas"]["guerra"])
        tipos = {a["tipo"] for a in plano["acoes"]}
        self.assertTrue(tipos & {"diferenciar_ou_sair", "canal_proprio", "reposicionar_preco"})

    def test_gap_baixo_enriquece_competir(self):
        analise = {
            "ok": True,
            "nickname": "NOVAMIX_COMERCIAL",
            "ameacas_preco": [
                {
                    "sku": "KIT-OK",
                    "meu_preco": 35.0,
                    "menor_preco_loja": 33.0,
                    "gap_pct": 6.0,
                }
            ],
            "estrategia": {},
        }
        produtos = [
            {
                "sku": "KIT-OK",
                "custo": 15.0,
                "canais": {"mercadolivre": {"preco": 35.0}},
            }
        ]
        with patch.object(ac, "NOVAMIX_GAP_COMPETIR_PCT", 10.0):
            plano = ac.gerar_plano_acoes_novamix(analise, produtos=produtos, max_acoes=5)
        self.assertEqual(plano["ads_sugerido"], "investir")
        self.assertIn("KIT-OK", plano["caixas"]["competir"])
        investir = [a for a in plano["acoes"] if a.get("tipo") == "investir_ads"]
        self.assertTrue(investir)
        self.assertEqual((investir[0].get("dados") or {}).get("ads_acao"), "investir")

    def test_formatar_secao_telegram(self):
        plano = {
            "ok": True,
            "ads_sugerido": "pausar",
            "caixas": {"guerra": ["SKU-A"], "competir": [], "observar": []},
            "acoes": [
                {
                    "titulo": "Sair de guerra SKU-A",
                    "detalhe": "Gap alto",
                    "prioridade": "alta",
                    "dados": {"ads_acao": "pausar"},
                }
            ],
        }
        txt = ac.formatar_secao_acoes_telegram(plano)
        self.assertIn("Plano de ação", txt)
        self.assertIn("Guerra", txt)
        self.assertIn("SKU-A", txt)
        self.assertIn("PAUSAR", txt)


class TestExecutarAdsNovamix(unittest.TestCase):
    @patch("integracoes.ml.ml_product_ads.aplicar_decisao_campanhas")
    @patch("integracoes.ml.ml_product_ads.probe_escrita_product_ads")
    @patch("core.notificador.perguntar_gestor_e_aguardar", return_value=True)
    @patch("core.notificador.alertar_gestor", return_value=True)
    def test_pausar_com_confirmacao(self, _alert, _perg, mock_probe, mock_aplicar):
        mock_probe.return_value = {"ok": True}
        mock_aplicar.return_value = [{"ok": True, "campaign_id": "C1"}]
        plano = {
            "ok": True,
            "ads_sugerido": "pausar",
            "caixas": {"guerra": ["SKU-A"], "competir": [], "observar": []},
        }
        with patch.object(ac, "NOVAMIX_AUTO_ADS_PAUSAR", True):
            out = ac.executar_acoes_ads_novamix(plano, pedir_confirmacao=True)
        self.assertTrue(out["executado"])
        self.assertEqual(out["decisao"], "pausar")
        mock_aplicar.assert_called_once()

    @patch("core.notificador.alertar_gestor", return_value=True)
    def test_investir_bloqueado_por_flag(self, _alert):
        plano = {"ok": True, "ads_sugerido": "investir", "caixas": {"competir": ["X"]}}
        with patch.object(ac, "NOVAMIX_AUTO_ADS_INVESTIR", False):
            out = ac.executar_acoes_ads_novamix(plano, pedir_confirmacao=False)
        self.assertFalse(out["executado"])
        self.assertIn("NOVAMIX_AUTO_ADS_INVESTIR", out["motivo"])

    def test_manter_nao_executa(self):
        out = ac.executar_acoes_ads_novamix(
            {"ok": True, "ads_sugerido": "manter", "caixas": {}},
            pedir_confirmacao=False,
        )
        self.assertFalse(out["executado"])
        self.assertIn("sem mudança", out["motivo"])


if __name__ == "__main__":
    unittest.main()
