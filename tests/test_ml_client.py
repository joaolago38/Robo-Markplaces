"""
tests/test_ml_client.py — ML01–ML13
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.ml import ml_client


def _mock_resp(body: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = body
    return r


class TestMlClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._patch = patch.multiple(
            ml_client,
            ML_ACCESS_TOKEN="tok",
            ML_SELLER_ID="111",
        )
        cls._patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML01_listar_perguntas_sucesso(self, _mock_en, mock_request):
        mock_request.return_value = _mock_resp({"questions": [{"id": "q1", "text": "Tem frete?"}]})
        out = ml_client.listar_perguntas_nao_respondidas()
        self.assertEqual(out, [{"id": "q1", "text": "Tem frete?"}])

    @patch.object(ml_client, "_enabled", return_value=False)
    def test_ML02_listar_perguntas_nao_configurado(self, *_patches):
        self.assertEqual(ml_client.listar_perguntas_nao_respondidas(), [])

    @patch.object(ml_client, "_request_ml", side_effect=Exception("boom"))
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML03_listar_perguntas_excecao(self, *_patches):
        self.assertEqual(ml_client.listar_perguntas_nao_respondidas(), [])

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML04_responder_pergunta_sucesso(self, _mock_en, mock_request):
        mock_request.return_value = _mock_resp({})
        self.assertTrue(ml_client.responder_pergunta("q1", "Sim, temos!"))

    @patch.object(ml_client, "_request_ml", side_effect=Exception("boom"))
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML05_responder_pergunta_excecao(self, *_patches):
        self.assertFalse(ml_client.responder_pergunta("q1", "texto"))

    @patch.object(ml_client, "_enabled", return_value=False)
    def test_ML06_responder_pergunta_nao_configurado(self, *_patches):
        self.assertFalse(ml_client.responder_pergunta("q1", "texto"))

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML07_buscar_reputacao(self, _mock_en, mock_request):
        mock_request.return_value = _mock_resp({"seller_reputation": {"level_id": "5_green"}})
        rep = ml_client.buscar_reputacao_vendedor()
        self.assertEqual(rep.get("level_id"), "5_green")

    @patch.object(ml_client, "_request_ml", side_effect=Exception("boom"))
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML08_buscar_reputacao_excecao(self, *_patches):
        self.assertEqual(ml_client.buscar_reputacao_vendedor(), {})

    @patch.object(ml_client, "dias_sem_acesso", return_value=0)
    @patch.object(ml_client, "registrar_acesso")
    @patch.object(ml_client, "listar_perguntas_nao_respondidas", return_value=[])
    @patch.object(ml_client, "buscar_reputacao_vendedor", return_value={})
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML09_obter_saude_conta(self, *_patches):
        saude = ml_client.obter_saude_conta()
        self.assertIn("configurado", saude)
        self.assertTrue(saude["configurado"])

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML10_atualizar_preco_sucesso(self, _mock_en, mock_request):
        mock_request.return_value = _mock_resp({})
        self.assertTrue(ml_client.atualizar_preco_item("MLB123", 59.90))

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML11_atualizar_estoque_sucesso(self, _mock_en, mock_request):
        mock_request.return_value = _mock_resp({})
        self.assertTrue(ml_client.atualizar_estoque_item("MLB123", 50))

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML12_listar_pedidos(self, _mock_en, mock_request):
        mock_request.return_value = _mock_resp({"results": [{"id": "1", "status": "paid"}]})
        pedidos = ml_client.listar_pedidos()
        self.assertGreaterEqual(len(pedidos), 1)

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML13_buscar_menor_preco_concorrente_float(self, _mock_en, mock_request):
        item_body = {"catalog_product_id": "CAT1"}
        concorrentes = {
            "results": [
                {"seller_id": 999, "price": 45.90},
                {"seller_id": 888, "price": 50.0},
            ]
        }
        mock_request.side_effect = [
            _mock_resp(item_body),
            _mock_resp(concorrentes),
        ]
        preco = ml_client.buscar_menor_preco_concorrente("MLB123")
        self.assertIsInstance(preco, float)

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML13b_buscar_detalhes_concorrentes(self, _mock_en, mock_request):
        item_body = {"catalog_product_id": "CAT1"}
        concorrentes = {
            "results": [
                {
                    "id": "MLB999",
                    "seller_id": 999,
                    "title": "Kit Concorrente",
                    "price": 45.90,
                    "condition": "new",
                    "sold_quantity": 12,
                    "shipping": {"free_shipping": True},
                },
            ]
        }
        mock_request.side_effect = [
            _mock_resp(item_body),
            _mock_resp(concorrentes),
        ]
        detalhes = ml_client.buscar_detalhes_concorrentes("MLB123", limite=5)
        self.assertEqual(len(detalhes), 1)
        self.assertEqual(detalhes[0]["titulo"], "Kit Concorrente")
        self.assertTrue(detalhes[0]["frete_gratis"])
        self.assertEqual(detalhes[0]["quantidade_vendida"], 12)


class TestMlAnuncioStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._patch = patch.multiple(ml_client, ML_ACCESS_TOKEN="tok", ML_SELLER_ID="111")
        cls._patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()

    def test_ML14_pausar_dry_run(self):
        out = ml_client.pausar_anuncio("MLB1", dry_run=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["status"], "paused")

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML15_pausar_confirmado(self, _en, mock_req):
        mock_req.return_value = _mock_resp({"status": "paused"})
        out = ml_client.pausar_anuncio("MLB1", dry_run=False, confirmar=True)
        self.assertTrue(out["ok"])
        self.assertFalse(out["dry_run"])
        mock_req.assert_called_once()

    def test_ML16_sem_confirmar_bloqueia(self):
        out = ml_client.encerrar_anuncio("MLB1", dry_run=False, confirmar=False)
        self.assertFalse(out["ok"])
        self.assertIn("confirmar", out["erro"])

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML17_encerrar_confirmado(self, _en, mock_req):
        mock_req.return_value = _mock_resp({"status": "closed"})
        out = ml_client.encerrar_anuncio("MLB1", dry_run=False, confirmar=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "closed")

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML18_obter_status(self, _en, mock_req):
        mock_req.return_value = _mock_resp({"status": "active", "title": "Esmalte"})
        out = ml_client.obter_status_anuncio("MLB1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "active")

    @patch.object(ml_client, "get_token_ml", return_value="novo_tok")
    @patch.object(ml_client, "request")
    def test_ML19_request_ml_retry_401(self, mock_request, _gt):
        r401 = MagicMock()
        r401.status_code = 401
        r200 = MagicMock()
        r200.status_code = 200
        mock_request.side_effect = [r401, r200]
        out = ml_client._request_ml("GET", f"{ml_client.BASE}/items/MLB1")
        self.assertEqual(out.status_code, 200)
        self.assertEqual(mock_request.call_count, 2)

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML20_funcoes_autenticadas_usam_request_ml(self, _en, mock_req):
        mock_req.return_value = _mock_resp({})
        ml_client.atualizar_preco_item("MLB1", 9.9)
        ml_client.atualizar_estoque_item("MLB1", 5)
        mock_req.return_value = _mock_resp({"results": []})
        ml_client.listar_pedidos(dias=1)
        mock_req.side_effect = [
            _mock_resp({"title": "Kit", "status": "active", "price": 10, "available_quantity": 1}),
            _mock_resp({"total_visits": 1}),
            _mock_resp({"total_visits": 2}),
        ]
        ml_client.buscar_metricas_item("MLB1")
        self.assertGreaterEqual(mock_req.call_count, 5)

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML21_atualizar_preco_bloqueado_kill_switch(self, _en, mock_req):
        with patch("core.guardrails.bloqueio_escrita_global", return_value={"ok": False, "erro": "ROBO_PAUSAR_ESCRITA"}):
            self.assertFalse(ml_client.atualizar_preco_item("MLB1", 10.0))
        mock_req.assert_not_called()

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML22_buscar_descricao_sucesso(self, _en, mock_req):
        mock_req.return_value = _mock_resp({"plain_text": "Descrição do kit Impala"})
        self.assertEqual(ml_client.buscar_descricao_item("MLB1"), "Descrição do kit Impala")

    @patch.object(ml_client, "_request_ml")
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML23_buscar_descricao_404(self, _en, mock_req):
        r = _mock_resp({})
        r.status_code = 404
        mock_req.return_value = r
        self.assertEqual(ml_client.buscar_descricao_item("MLB1"), "")

    @patch.object(ml_client, "_request_ml", side_effect=RuntimeError("rede"))
    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML24_buscar_descricao_excecao(self, *_):
        self.assertEqual(ml_client.buscar_descricao_item("MLB1"), "")

    @patch.object(ml_client, "_enabled", return_value=False)
    def test_ML25_buscar_descricao_nao_configurado(self, *_):
        self.assertEqual(ml_client.buscar_descricao_item("MLB1"), "")

    @patch.object(ml_client, "_enabled", return_value=True)
    def test_ML26_buscar_descricao_item_id_vazio(self, *_):
        self.assertEqual(ml_client.buscar_descricao_item(""), "")
        self.assertEqual(ml_client.buscar_descricao_item("   "), "")


if __name__ == "__main__":
    unittest.main()
