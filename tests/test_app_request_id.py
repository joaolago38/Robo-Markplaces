"""
tests/test_app_request_id.py — middleware de correlation id (request_id) em api/app.py.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.app import app
from core.request_context import definir_request_id, obter_request_id


class TestRequestIdMiddleware(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def tearDown(self):
        definir_request_id(None)

    def test_health_retorna_header_request_id(self):
        resp = self.client.get("/health")
        self.assertIn("X-Request-Id", resp.headers)
        self.assertTrue(len(resp.headers["X-Request-Id"]) > 0)

    def test_request_ids_diferentes_entre_chamadas(self):
        resp1 = self.client.get("/health")
        resp2 = self.client.get("/health")
        self.assertNotEqual(resp1.headers["X-Request-Id"], resp2.headers["X-Request-Id"])

    def test_respeita_request_id_recebido_no_header(self):
        resp = self.client.get("/health", headers={"X-Request-Id": "meu-id-123"})
        self.assertEqual(resp.headers["X-Request-Id"], "meu-id-123")


if __name__ == "__main__":
    unittest.main()
