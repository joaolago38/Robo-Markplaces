"""tests/test_resumo_conta_ml.py"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from integracoes.ml import resumo_conta as rc


class TestResumoContaMl(unittest.TestCase):
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
        self.assertIn("API claims indisponivel", msg)
        self.assertIn("Ao alcançar 10 vendas", msg)

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
        self.assertIn("Todos os anúncios estão pausados", msg)

    def test_mensagem_erro(self):
        msg = rc.montar_mensagem_telegram({"ok": False, "erro": "ml_nao_configurado"})
        self.assertIn("Falha", msg)


if __name__ == "__main__":
    unittest.main()
