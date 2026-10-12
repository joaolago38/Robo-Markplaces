"""
tests/test_lambda_handler.py — entrada Lambda para Flask.
"""
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestLambdaHandler(unittest.TestCase):
    def test_handler_delega_para_serverless_wsgi(self):
        # Evita import real do Flask app / serverless_wsgi no ambiente sem deps.
        fake_wsgi = types.ModuleType("serverless_wsgi")
        fake_wsgi.handle_request = MagicMock(return_value={"statusCode": 200})
        fake_app_mod = types.ModuleType("api.app")
        fake_app_mod.app = MagicMock(name="flask_app")

        with patch.dict(
            sys.modules,
            {
                "serverless_wsgi": fake_wsgi,
                "api.app": fake_app_mod,
            },
        ):
            import importlib

            import api.lambda_handler as lh

            lh = importlib.reload(lh)
            event = {"httpMethod": "GET", "path": "/health"}
            context = MagicMock()
            out = lh.handler(event, context)

        fake_wsgi.handle_request.assert_called_once()
        self.assertEqual(out["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
