"""
tests/test_request_context.py — correlation id (request_id) por requisição.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import request_context


class TestRequestContext(unittest.TestCase):
    def tearDown(self):
        request_context.definir_request_id(None)

    def test_sem_request_id_definido_retorna_none(self):
        self.assertIsNone(request_context.obter_request_id())

    def test_definir_e_obter_request_id(self):
        request_context.definir_request_id("abc123")
        self.assertEqual(request_context.obter_request_id(), "abc123")

    def test_novo_request_id_gera_string_curta_unica(self):
        rid1 = request_context.novo_request_id()
        rid2 = request_context.novo_request_id()
        self.assertNotEqual(rid1, rid2)
        self.assertEqual(len(rid1), 12)


if __name__ == "__main__":
    unittest.main()
