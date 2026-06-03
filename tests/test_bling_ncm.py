"""
tests/test_bling_ncm.py
Testes (mockados, sem rede) para o cadastro de NCM no Bling.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.bling import bling_client as bc


def _resp(json_data=None):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = json_data if json_data is not None else {}
    r.raise_for_status = MagicMock()
    return r


class TestBlingNCM(unittest.TestCase):
    def test_atualizar_ncm_read_modify_write(self):
        """GET completo -> altera só ncm -> PUT com o objeto inteiro preservado."""
        produto = {"id": 123, "nome": "Copo", "preco": 10.0, "ncm": "", "outroCampo": "manter"}
        chamadas = []

        def fake(method, url, **kw):
            chamadas.append((method, url, kw.get("json")))
            if method == "GET":
                return _resp({"data": produto})
            return _resp({"data": {"id": 123}})

        with patch.object(bc, "request", side_effect=fake):
            res = bc.atualizar_ncm_produto(123, "8517.62.99")

        self.assertTrue(res["ok"])
        self.assertEqual(res["ncm"], "85176299")
        # O PUT deve ter recebido o objeto completo, com ncm novo e os outros campos.
        put = [c for c in chamadas if c[0] == "PUT"][0]
        self.assertEqual(put[2]["ncm"], "85176299")
        self.assertEqual(put[2]["outroCampo"], "manter")
        self.assertEqual(put[2]["nome"], "Copo")

    def test_ncm_invalido_nao_chama_api(self):
        with patch.object(bc, "request") as req:
            res = bc.atualizar_ncm_produto(1, "123")  # menos de 8 dígitos
        req.assert_not_called()
        self.assertFalse(res["ok"])
        self.assertIn("inválido", res["erro"])

    def test_definir_ncm_por_sku_resolve_id(self):
        def fake(method, url, **kw):
            if method == "GET" and url.endswith("/produtos"):
                return _resp({"data": [{"id": 555, "codigo": "SKU1", "ncm": ""}]})
            if method == "GET":  # GET /produtos/555
                return _resp({"data": {"id": 555, "codigo": "SKU1", "ncm": ""}})
            return _resp({"data": {"id": 555}})

        with patch.object(bc, "request", side_effect=fake):
            res = bc.definir_ncm_por_sku("SKU1", "61091000")

        self.assertTrue(res["ok"])
        self.assertEqual(res["sku"], "SKU1")
        self.assertEqual(res["produto_id"], 555)

    def test_definir_ncm_sku_inexistente(self):
        with patch.object(bc, "request", return_value=_resp({"data": []})):
            res = bc.definir_ncm_por_sku("NAO_EXISTE", "61091000")
        self.assertFalse(res["ok"])
        self.assertIn("não encontrado", res["erro"])


if __name__ == "__main__":
    unittest.main()
