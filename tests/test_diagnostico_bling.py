"""
tests/test_diagnostico_bling.py
Testes de scripts/diagnostico_bling.py
Behaviors cobertos:
  - DB01: testar_token retorna ok=True quando API responde 200
  - DB02: testar_token retorna ok=False com status=401 quando expirado
  - DB03: testar_token retorna ok=False quando token ausente
  - DB04: testar_produtos retorna lista de produtos em sucesso
  - DB05: testar_produtos retorna lista vazia em exceção
  - DB06: testar_empresa retorna razão social e cidade em sucesso
  - DB07: testar_nfe retorna ok=True quando endpoint acessível
  - DB08: testar_nfe retorna ok=False com status=403 sem permissão
  - DB09: testar_refresh retorna novos tokens em sucesso
  - DB10: testar_refresh retorna ok=False sem credenciais
  - DB11: executar retorna score_pct entre 0 e 100
  - DB12: executar mostra tokens renovados quando token expirado
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mock_resp(body: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.text = str(body)
    return r


class TestTestarToken(unittest.TestCase):

    # DB01
    @patch("scripts.diagnostico_bling.ACCESS_TOKEN", "tok_valido")
    @patch("scripts.diagnostico_bling.requests.get")
    def test_DB01_token_valido_retorna_ok(self, mock_get):
        mock_get.return_value = _mock_resp({"data": []}, 200)
        from scripts.diagnostico_bling import testar_token
        r = testar_token()
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], 200)

    # DB02
    @patch("scripts.diagnostico_bling.ACCESS_TOKEN", "tok_expirado")
    @patch("scripts.diagnostico_bling.requests.get")
    def test_DB02_token_expirado_retorna_401(self, mock_get):
        mock_get.return_value = _mock_resp({}, 401)
        from scripts.diagnostico_bling import testar_token
        r = testar_token()
        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], 401)
        self.assertIn("EXPIRADO", r["msg"])

    # DB03
    @patch("scripts.diagnostico_bling.ACCESS_TOKEN", "")
    def test_DB03_token_ausente_retorna_falso(self):
        from scripts.diagnostico_bling import testar_token
        r = testar_token()
        self.assertFalse(r["ok"])
        self.assertIn("não configurado", r["msg"])


class TestTestarProdutos(unittest.TestCase):

    # DB04
    @patch("scripts.diagnostico_bling.ACCESS_TOKEN", "tok")
    @patch("scripts.diagnostico_bling.requests.get")
    def test_DB04_lista_produtos_em_sucesso(self, mock_get):
        mock_get.return_value = _mock_resp({
            "data": [
                {"codigo": "KIT-1", "nome": "Kit Impala", "preco": 59.9,
                 "estoque": {"saldoVirtualTotal": 50}},
            ]
        }, 200)
        from scripts.diagnostico_bling import testar_produtos
        r = testar_produtos()
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["produtos"]), 1)
        self.assertIn("1 produto", r["msg"])

    # DB05
    @patch("scripts.diagnostico_bling.ACCESS_TOKEN", "tok")
    @patch("scripts.diagnostico_bling.requests.get", side_effect=Exception("timeout"))
    def test_DB05_retorna_vazio_em_excecao(self, _):
        from scripts.diagnostico_bling import testar_produtos
        r = testar_produtos()
        self.assertFalse(r["ok"])
        self.assertEqual(r["produtos"], [])


class TestTestarEmpresa(unittest.TestCase):

    # DB06
    @patch("scripts.diagnostico_bling.ACCESS_TOKEN", "tok")
    @patch("scripts.diagnostico_bling.requests.get")
    def test_DB06_retorna_razao_e_cidade(self, mock_get):
        mock_get.return_value = _mock_resp({
            "data": {
                "razaoSocial": "COMERCIAL LAGO OLIVEIRA LTDA",
                "cnpj":        "52.668.583/0001-27",
                "endereco":    {"municipio": "Campinas"},
            }
        }, 200)
        from scripts.diagnostico_bling import testar_empresa
        r = testar_empresa()
        self.assertTrue(r["ok"])
        self.assertIn("COMERCIAL", r["razao"])
        self.assertEqual(r["cidade"], "Campinas")


class TestTestarNFe(unittest.TestCase):

    # DB07
    @patch("scripts.diagnostico_bling.ACCESS_TOKEN", "tok")
    @patch("scripts.diagnostico_bling.requests.get")
    def test_DB07_nfe_acessivel_retorna_ok(self, mock_get):
        mock_get.return_value = _mock_resp({"data": []}, 200)
        from scripts.diagnostico_bling import testar_nfe
        r = testar_nfe()
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], 200)

    # DB08
    @patch("scripts.diagnostico_bling.ACCESS_TOKEN", "tok")
    @patch("scripts.diagnostico_bling.requests.get")
    def test_DB08_403_sem_permissao(self, mock_get):
        mock_get.return_value = _mock_resp({}, 403)
        from scripts.diagnostico_bling import testar_nfe
        r = testar_nfe()
        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], 403)
        self.assertIn("permissão", r["msg"])


class TestTestarRefresh(unittest.TestCase):

    # DB09
    @patch("scripts.diagnostico_bling.CLIENT_ID",     "cid")
    @patch("scripts.diagnostico_bling.CLIENT_SECRET", "csec")
    @patch("scripts.diagnostico_bling.REFRESH_TOKEN", "ref")
    @patch("scripts.diagnostico_bling.requests.post")
    def test_DB09_refresh_retorna_novos_tokens(self, mock_post):
        mock_post.return_value = _mock_resp({
            "access_token":  "novo_access",
            "refresh_token": "novo_refresh",
            "expires_in":    21600,
        }, 200)
        from scripts.diagnostico_bling import testar_refresh
        r = testar_refresh()
        self.assertTrue(r["ok"])
        self.assertEqual(r["access_token"], "novo_access")
        self.assertEqual(r["refresh_token"], "novo_refresh")

    # DB10
    @patch("scripts.diagnostico_bling.CLIENT_ID",     "")
    @patch("scripts.diagnostico_bling.CLIENT_SECRET", "")
    @patch("scripts.diagnostico_bling.REFRESH_TOKEN", "")
    def test_DB10_sem_credenciais_retorna_falso(self):
        from scripts.diagnostico_bling import testar_refresh
        r = testar_refresh()
        self.assertFalse(r["ok"])
        self.assertIn("ausentes", r["msg"])


class TestExecutar(unittest.TestCase):

    # DB11
    @patch("scripts.diagnostico_bling.ACCESS_TOKEN", "tok")
    @patch("scripts.diagnostico_bling.requests.get")
    @patch("scripts.diagnostico_bling.requests.post")
    def test_DB11_executar_retorna_score_entre_0_e_100(self, mock_post, mock_get):
        resp_ok  = _mock_resp({"data": []}, 200)
        mock_get.return_value  = resp_ok
        mock_post.return_value = _mock_resp(
            {"access_token": "A", "refresh_token": "R", "expires_in": 21600}, 200
        )
        from scripts.diagnostico_bling import executar
        r = executar()
        self.assertIn("score_pct", r)
        self.assertGreaterEqual(r["score_pct"], 0)
        self.assertLessEqual(r["score_pct"], 100)

    # DB12
    @patch("scripts.diagnostico_bling.ACCESS_TOKEN", "tok_expirado")
    @patch("scripts.diagnostico_bling.CLIENT_ID",     "cid")
    @patch("scripts.diagnostico_bling.CLIENT_SECRET", "csec")
    @patch("scripts.diagnostico_bling.REFRESH_TOKEN", "ref")
    @patch("scripts.diagnostico_bling.requests.get")
    @patch("scripts.diagnostico_bling.requests.post")
    def test_DB12_renovacao_automatica_quando_token_expirado(self, mock_post, mock_get):
        # GET retorna 401 (expirado) exceto para escopos
        mock_get.return_value = _mock_resp({}, 401)
        # POST retorna token novo
        mock_post.return_value = _mock_resp(
            {"access_token": "NOVO_ACCESS", "refresh_token": "NOVO_REFRESH", "expires_in": 21600}, 200
        )
        from scripts.diagnostico_bling import executar
        r = executar()
        # Deve ter tentado renovar
        mock_post.assert_called()
        self.assertIn("score_pct", r)


if __name__ == "__main__":
    unittest.main()
