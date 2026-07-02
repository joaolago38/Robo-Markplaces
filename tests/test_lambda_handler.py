"""
tests/test_lambda_handler.py — entrada Lambda para Flask.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestLambdaHandler(unittest.TestCase):
    @patch("api.lambda_handler.serverless_wsgi.handle_request", return_value={"statusCode": 200})
    @patch("api.lambda_handler.app")
    def test_handler_delega_para_serverless_wsgi(self, _app, mock_handle):
        from api.lambda_handler import handler

        event = {"httpMethod": "GET", "path": "/health"}
        context = MagicMock()
        out = handler(event, context)
        mock_handle.assert_called_once()
        self.assertEqual(out["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
