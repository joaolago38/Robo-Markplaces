"""tests/test_resumo_conta_ml.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.ml import resumo_conta as rc


class TestResumoContaMl(unittest.TestCase):
    def setUp(self):
        from integracoes.ml.filtro_anuncios_conta import reset_ultimo_filtro

        reset_ultimo_filtro()
    def test_texto_reputacao_sem_cor(self):
        out = rc._texto_reputacao({"level_id": None, "transactions": {"completed": 3}})
        self.assertTrue(out["sem_cor"])
        self.assertIn("Sem cor", out["cor"])

    def test_texto_reputacao_verde(self):
        out = rc._texto_reputacao(
            {
                "level_id": "5_green",
                "transactions": {"completed": 50},
                "metrics": {"claims": {"rate": 0.01}},
                "power_seller_status": "gold",
            }
        )
        self.assertEqual(out["cor"], "Verde")
        self.assertFalse(out["sem_cor"])
        self.assertEqual(out["claims_rate"], 0.01)
        self.assertEqual(out["nivel_num"], 5)
        self.assertEqual(out["power_num"], 2)

    def test_emitir_metricas_saude_conta(self):
        resumo = {
            "ok": True,
            "anuncios_ativos": 2,
            "anuncios_pausados": 0,
            "anuncios_a_melhorar_total": 1,
            "perguntas_pendentes": 3,
            "envios_pendentes": 0,
            "pos_venda_claims": 0,
            "precos_pendencias_total": 0,
            "reputacao": {
                "vendas_completadas": 12,
                "vendas_60d": 4,
                "avaliacoes": 8,
                "nota": 4.9,
                "claims_rate": 0.01,
                "atraso_rate": 0,
                "cancelamentos_rate": 0,
                "nivel_num": 5,
                "power_num": 2,
                "sem_cor": False,
            },
        }
        with patch("core.datadog_metrics.gauge") as mock_g:
            rc.emitir_metricas_saude_conta(resumo)
        nomes = [c.args[0] for c in mock_g.call_args_list]
        self.assertIn("ml.saude.vendas_completadas", nomes)
        self.assertIn("ml.saude.avaliacoes", nomes)
        self.assertIn("ml.saude.anuncios_ativos", nomes)
        self.assertIn("ml.saude.anuncios_premium", nomes)
        self.assertIn("ml.saude.anuncios_classico", nomes)
        self.assertIn("ml.saude.todos_pausados", nomes)
        self.assertIn("ml.saude.anuncios_ignorados_fora_foco", nomes)
        self.assertIn("ml.saude.catalogo_foco_vazio", nomes)
        self.assertIn("ml.saude.anuncios_ativos_conta", nomes)
        self.assertIn("ml.saude.anuncios_pausados_conta", nomes)
        self.assertIn("ml.saude.conta_ok", nomes)
        pares = {c.args[0]: c.args[1] for c in mock_g.call_args_list}
        self.assertEqual(pares["ml.saude.ok"], 1.0)
        self.assertEqual(pares["ml.saude.conta_ok"], 1.0)
        self.assertEqual(pares["ml.saude.vendas_completadas"], 12.0)
        self.assertEqual(pares["ml.saude.claims_rate_pct"], 1.0)
        self.assertEqual(pares["ml.saude.todos_pausados"], 0.0)

    def test_emitir_metricas_saude_falha(self):
        with patch("core.datadog_metrics.gauge") as mock_g:
            rc.emitir_metricas_saude_conta({"ok": False})
        pares = {c.args[0]: c.args[1] for c in mock_g.call_args_list}
        self.assertEqual(pares["ml.saude.ok"], 0.0)
        self.assertEqual(pares["ml.saude.conta_ok"], 0.0)

    def test_emitir_metricas_saude_conta_laranja(self):
        resumo = {
            "ok": True,
            "reputacao": {
                "cor": "Laranja",
                "level_id": "2_orange",
                "claims_rate": 0.0,
                "atraso_rate": 0.0,
                "cancelamentos_rate": 0.0,
            },
        }
        with patch("core.datadog_metrics.gauge") as mock_g:
            rc.emitir_metricas_saude_conta(resumo)
        pares = {c.args[0]: c.args[1] for c in mock_g.call_args_list}
        self.assertEqual(pares["ml.saude.ok"], 1.0)
        self.assertEqual(pares["ml.saude.conta_ok"], 0.0)

    @patch("integracoes.ml.integridade_dados_ml.executar", return_value={"pct": 100.0, "atinge_meta": True, "espelho_confiavel": True, "meta_pct": 99.99, "corrigidos": 0})
    @patch("integracoes.ml.ml_product_ads.listar_campanhas", return_value=[{"status": "IDLE"}])
    @patch.object(rc.ml_client, "buscar_sugestao_preco", return_value={})
    @patch.object(rc.ml_client, "listar_itens_com_sugestao_preco", return_value=[])
    @patch.object(
        rc.ml_client,
        "buscar_performance_item",
        return_value={
            "a_melhorar": True,
            "score": 40,
            "level_wording": "Básica",
            "regras_pendentes": [{"titulo": "Adicionar fotos"}],
        },
    )
    @patch.object(
        rc.ml_client,
        "listar_meus_anuncios",
        return_value=[
            {
                "item_id": "MLB1",
                "titulo": "Esmalte teste",
                "preco": 9.9,
                "sold_quantity": 0,
                "status": "active",
                "listing_type_id": "gold_pro",
            }
        ],
    )
    @patch.object(rc.ml_client, "contar_claims_abertos", return_value={"ok": False, "total": 0, "motivo": "claims_indisponivel"})
    @patch.object(rc.ml_client, "contar_envios_pendentes", return_value={"ok": True, "total": 0})
    @patch.object(rc.ml_client, "listar_perguntas_nao_respondidas", return_value=[])
    @patch.object(
        rc.ml_client,
        "buscar_perfil_vendedor",
        return_value={
            "id": "123",
            "nickname": "LOJA_TESTE",
            "seller_reputation": {"level_id": None, "transactions": {"completed": 2}},
        },
    )
    @patch.object(rc, "ML_ACCESS_TOKEN", "tok")
    @patch.object(rc, "ML_SELLER_ID", "123")
    def test_coletar_e_montar_mensagem(self, *_mocks):
        resumo = rc.coletar_resumo_conta(max_anuncios_performance=10)
        self.assertTrue(resumo["ok"])
        self.assertEqual(resumo["anuncios_a_melhorar_total"], 1)
        self.assertEqual(resumo["anuncios_ativos"], 1)
        self.assertEqual(resumo["anuncios_pausados"], 0)
        self.assertEqual(resumo["nickname"], "LOJA_TESTE")
        msg = rc.montar_mensagem_telegram(resumo)
        self.assertIn("Resumo da conta", msg)
        self.assertIn("Anúncios a melhorar", msg)
        self.assertIn("LOJA_TESTE", msg)
        self.assertIn("MLB1", msg)
        self.assertEqual(resumo["anuncios_premium"], 1)
        self.assertEqual(resumo["anuncios_classico"], 0)
        self.assertIn("Premium", msg)
        self.assertIn("API claims indisponivel", msg)
        self.assertIn("Integridade ML", msg)
        self.assertIn("99.99", msg)

    @patch("integracoes.ml.integridade_dados_ml.executar", return_value={"pct": 100.0, "atinge_meta": True, "espelho_confiavel": True, "meta_pct": 99.99, "corrigidos": 0})
    @patch("integracoes.ml.ml_product_ads.listar_campanhas", return_value=[])
    @patch.object(rc.ml_client, "buscar_sugestao_preco", return_value={})
    @patch.object(rc.ml_client, "listar_itens_com_sugestao_preco", return_value=[])
    @patch.object(rc.ml_client, "buscar_performance_item", return_value={})
    @patch.object(
        rc.ml_client,
        "listar_meus_anuncios",
        return_value=[
            {
                "item_id": "MLB2",
                "titulo": "Item pausado",
                "preco": 10.0,
                "sold_quantity": 0,
                "status": "paused",
            }
        ],
    )
    @patch.object(rc.ml_client, "contar_claims_abertos", return_value={"ok": True, "total": 0})
    @patch.object(rc.ml_client, "contar_envios_pendentes", return_value={"ok": True, "total": 0})
    @patch.object(rc.ml_client, "listar_perguntas_nao_respondidas", return_value=[])
    @patch.object(
        rc.ml_client,
        "buscar_perfil_vendedor",
        return_value={"id": "1", "nickname": "X", "seller_reputation": {}},
    )
    @patch.object(rc, "ML_ACCESS_TOKEN", "tok")
    @patch.object(rc, "ML_SELLER_ID", "1")
    def test_anuncio_pausado_conta_como_a_melhorar(self, *_mocks):
        resumo = rc.coletar_resumo_conta(max_anuncios_performance=10)
        self.assertTrue(resumo["ok"])
        self.assertEqual(resumo["anuncios_pausados"], 1)
        self.assertEqual(resumo["anuncios_a_melhorar_total"], 1)
        self.assertEqual(resumo["anuncios_a_melhorar"][0]["acoes"], ["Reativar anúncio"])
        msg = rc.montar_mensagem_telegram(resumo)
        self.assertIn("Todos os anúncios do foco estão pausados", msg)

    def test_mensagem_bolsas_ignoradas_nao_pede_reativar(self):
        resumo = {
            "ok": True,
            "nickname": "LOJA",
            "seller_id": "1",
            "perguntas_pendentes": 0,
            "anuncios_a_melhorar_total": 0,
            "anuncios_total": 0,
            "anuncios_ativos": 0,
            "anuncios_pausados": 0,
            "anuncios_ignorados_fora_foco": 38,
            "precos_pendencias_total": 0,
            "publicidade_recomendacoes": 0,
            "envios_pendentes": 0,
            "envios_ok": True,
            "pos_venda_claims": 0,
            "pos_venda_ok": True,
            "faturamento_nota": "ok",
            "reputacao": {
                "cor": "Verde",
                "vendas_completadas": 50,
                "avaliacoes": 20,
                "nota": 4.9,
                "claims_rate": 0,
                "power_seller": "—",
                "sem_cor": False,
            },
        }
        msg = rc.montar_mensagem_telegram(resumo)
        self.assertIn("38 anúncio(s) de bolsas/legado ignorados", msg)
        self.assertIn("Reputação da conta continua valendo", msg)
        self.assertIn("Nenhum anúncio do foco no ar", msg)
        self.assertNotIn("reative para voltar a vender", msg)

    def test_mensagem_erro(self):
        msg = rc.montar_mensagem_telegram({"ok": False, "erro": "ml_nao_configurado"})
        self.assertIn("Falha", msg)


if __name__ == "__main__":
    unittest.main()
