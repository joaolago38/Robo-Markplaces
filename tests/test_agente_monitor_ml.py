"""
tests/test_agente_monitor_ml.py
Cobre o agente de monitoramento ML (somente leitura / recomendações).
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentes.ml import agente_monitor_ml as mon


class TestAnalisar(unittest.TestCase):
    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon.ml_client, "_enabled", return_value=False)
    def test_ml_nao_configurado(self, *_):
        out = mon.analisar(enviar_alerta=True)
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "ML não configurado")
        self.assertTrue(out["enviado"])

    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon.ml_client, "_enabled", return_value=True)
    @patch.object(mon.ml_client, "listar_meus_anuncios", return_value=[])
    @patch.object(mon.ml_product_ads, "campanhas_acos_acima_limite", return_value=[])
    @patch.object(mon.ml_product_ads, "listar_campanhas", return_value=[])
    @patch.object(mon.ml_product_ads, "obter_advertiser", return_value={"ok": False, "codigo": "sem_permissao"})
    @patch.object(mon.ml_client, "buscar_reputacao_vendedor", return_value={})
    @patch.object(mon.ml_client, "listar_perguntas_nao_respondidas", return_value=[{"text": "oi"}])
    @patch.object(mon.ml_client, "obter_saude_conta", return_value={"pendencias": 1, "claims_rate": 0.0, "dias_sem_acesso": 0})
    def test_analisar_com_perguntas_pendentes(self, *_):
        out = mon.analisar(enviar_alerta=False, limite_itens=0)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(len(out["recomendacoes"]), 1)
        self.assertIn("Responder", out["recomendacoes"][0])
        self.assertIn("📊", out["resumo"])

    @patch.object(mon, "time")
    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon.ml_client, "_enabled", return_value=True)
    @patch.object(mon.ml_client, "buscar_sugestao_preco", return_value={
        "aplicavel": True,
        "preco_sugerido": 45.0,
        "percent_difference": -10.0,
    })
    @patch.object(mon.ml_client, "buscar_acos_ads", return_value=0.0)
    @patch.object(mon.ml_client, "buscar_detalhes_concorrentes", return_value=[])
    @patch.object(mon.ml_client, "buscar_menor_preco_concorrente", return_value=0.0)
    @patch.object(mon.ml_client, "buscar_metricas_item", return_value={"preco": 60.0, "visitas_7d": 10, "visitas_30d": 100, "titulo": "Kit"})
    @patch.object(mon.ml_client, "listar_meus_anuncios", return_value=[{"item_id": "MLB1", "titulo": "Kit", "preco": 60.0}])
    @patch.object(mon.ml_product_ads, "campanhas_acos_acima_limite", return_value=[])
    @patch.object(mon.ml_product_ads, "listar_campanhas", return_value=[])
    @patch.object(mon.ml_product_ads, "obter_advertiser", return_value={"ok": True, "advertiser_id": "adv1"})
    @patch.object(mon.ml_client, "buscar_reputacao_vendedor", return_value={})
    @patch.object(mon.ml_client, "listar_perguntas_nao_respondidas", return_value=[])
    @patch.object(mon.ml_client, "obter_saude_conta", return_value={"pendencias": 0, "claims_rate": 0.0, "dias_sem_acesso": 0})
    def test_alerta_sugestao_preco_ml(self, *_):
        out = mon.analisar(enviar_alerta=False, limite_itens=1)
        self.assertTrue(out["ok"])
        self.assertTrue(any("ML sugere" in r for r in out["recomendacoes"]))
        conc = out["concorrencia"][0]
        self.assertIn("sugestao_preco", conc)
        self.assertTrue(conc["sugestao_preco"].get("aplicavel"))

    @patch.object(mon, "time")
    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon.ml_client, "_enabled", return_value=True)
    @patch.object(mon.ml_client, "buscar_sugestao_preco", return_value={})
    @patch.object(mon.ml_client, "buscar_acos_ads", return_value=0.0)
    @patch.object(mon.ml_client, "buscar_detalhes_concorrentes", return_value=[
        {"id": "MLB9", "titulo": "Concorrente", "preco": 50.0, "frete_gratis": True, "condicao": "new", "quantidade_vendida": 10}
    ])
    @patch.object(mon.ml_client, "buscar_menor_preco_concorrente", return_value=50.0)
    @patch.object(mon.ml_client, "buscar_metricas_item", return_value={"preco": 60.0, "visitas_7d": 10, "visitas_30d": 100, "titulo": "Kit"})
    @patch.object(mon.ml_client, "listar_meus_anuncios", return_value=[{"item_id": "MLB1", "titulo": "Kit", "preco": 60.0}])
    @patch.object(mon.ml_product_ads, "campanhas_acos_acima_limite", return_value=[])
    @patch.object(mon.ml_product_ads, "listar_campanhas", return_value=[{"nome": "C1", "status": "active", "cost": 10, "acos": 0.1, "roas": 2, "clicks": 5}])
    @patch.object(mon.ml_product_ads, "obter_advertiser", return_value={"ok": True, "advertiser_id": "adv1"})
    @patch.object(mon.ml_client, "buscar_reputacao_vendedor", return_value={})
    @patch.object(mon.ml_client, "listar_perguntas_nao_respondidas", return_value=[])
    @patch.object(mon.ml_client, "obter_saude_conta", return_value={"pendencias": 0, "claims_rate": 0.0, "dias_sem_acesso": 0})
    def test_preco_acima_concorrente(self, *_):
        out = mon.analisar(enviar_alerta=False, limite_itens=1)
        self.assertTrue(out["ok"])
        self.assertTrue(any("revisar preço" in r.lower() for r in out["recomendacoes"]))
        conc = out["concorrencia"][0]
        self.assertIn("concorrentes", conc)
        self.assertEqual(conc["concorrentes"][0]["titulo"], "Concorrente")

    @patch.object(mon, "time")
    @patch.object(mon, "alertar_gestor", return_value=True)
    @patch.object(mon.ml_client, "_enabled", return_value=True)
    @patch.object(mon.ml_client, "buscar_sugestao_preco", return_value={})
    @patch.object(mon.ml_client, "buscar_acos_ads", return_value=0.0)
    @patch.object(mon.ml_client, "buscar_detalhes_concorrentes", return_value=[])
    @patch.object(mon.ml_client, "buscar_menor_preco_concorrente")
    @patch.object(
        mon.ml_client,
        "buscar_metricas_item",
        return_value={
            "preco": 44.9,
            "visitas_7d": 10,
            "visitas_30d": 100,
            "titulo": "Kit MIMO",
            "listing_type_id": "gold_pro",
        },
    )
    @patch.object(
        mon.ml_client,
        "listar_meus_anuncios",
        return_value=[
            {
                "item_id": "MLB1",
                "titulo": "Kit MIMO",
                "preco": 44.9,
                "listing_type_id": "gold_pro",
            }
        ],
    )
    @patch.object(mon.ml_product_ads, "campanhas_acos_acima_limite", return_value=[])
    @patch.object(mon.ml_product_ads, "listar_campanhas", return_value=[])
    @patch.object(mon.ml_product_ads, "obter_advertiser", return_value={"ok": True, "advertiser_id": "adv1"})
    @patch.object(mon.ml_client, "buscar_reputacao_vendedor", return_value={})
    @patch.object(mon.ml_client, "listar_perguntas_nao_respondidas", return_value=[])
    @patch.object(mon.ml_client, "obter_saude_conta", return_value={"pendencias": 0, "claims_rate": 0.0, "dias_sem_acesso": 0})
    def test_nao_alerta_igualar_preco_de_outra_prateleira(
        self,
        _saude,
        _perguntas,
        _rep,
        _adv,
        _camp,
        _acos_lim,
        _listar,
        _metricas,
        mock_menor,
        *_rest,
    ):

        def _menor(_item_id, mesma_prateleira=True):
            return 50.0 if mesma_prateleira else 22.0

        mock_menor.side_effect = _menor
        out = mon.analisar(enviar_alerta=False, limite_itens=1)
        self.assertTrue(out["ok"])
        recs = " ".join(out["recomendacoes"])
        self.assertIn("não igualar preço", recs)
        self.assertNotIn("revisar preço", recs.lower())

    @patch.object(mon, "analisar", return_value={"ok": True, "resumo": "ok", "recomendacoes": [], "enviado": True})
    def test_main_imprime_resumo(self, *_):
        self.assertEqual(mon.main(), 0)


class TestHelpers(unittest.TestCase):
    def test_pct_diff(self):
        self.assertEqual(mon._pct_diff(105.0, 100.0), 5.0)
        self.assertEqual(mon._pct_diff(10.0, 0.0), 0.0)

    def test_max_itens_analise_vem_do_config(self):
        import core.config as cfg

        self.assertEqual(mon.MAX_ITENS_ANALISE, cfg.ML_MAX_ITENS_ANALISE)


if __name__ == "__main__":
    unittest.main()
