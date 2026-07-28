"""
tests/test_meta_client.py
Cobre publicar_facebook e publicar_instagram (todos os ramos).
"""
import os
import sys
import unittest
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.meta import meta_client as mc
from tests.http_fixtures import make_http_response


@pytest.mark.usefixtures("env_tokens")
class TestPublicarFacebook(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _http(self, mock_http):
        self.mock_http = mock_http

    @patch.object(mc, "META_PAGE_ID", "")
    @patch.object(mc, "META_ACCESS_TOKEN", "")
    def test_sem_config(self, *_):
        self.assertFalse(mc.publicar_facebook("oi"))

    @patch.object(mc, "META_PAGE_ID", "page1")
    @patch.object(mc, "META_ACCESS_TOKEN", "tok")
    def test_ok(self):
        self.mock_http.return_value = make_http_response(json_body={"id": "post1"})
        self.assertTrue(mc.publicar_facebook("oi"))

    @patch.object(mc, "META_PAGE_ID", "page1")
    @patch.object(mc, "META_ACCESS_TOKEN", "tok")
    def test_erro(self):
        self.mock_http.side_effect = Exception("boom")
        self.assertFalse(mc.publicar_facebook("oi"))


@pytest.mark.usefixtures("env_tokens")
class TestPublicarInstagram(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _http(self, mock_http):
        self.mock_http = mock_http

    @patch.object(mc, "META_INSTAGRAM_ID", "")
    @patch.object(mc, "META_ACCESS_TOKEN", "")
    def test_sem_config(self, *_):
        self.assertFalse(mc.publicar_instagram("oi", "http://img"))

    @patch.object(mc, "META_INSTAGRAM_ID", "ig1")
    @patch.object(mc, "META_ACCESS_TOKEN", "tok")
    def test_sem_imagem(self, *_):
        self.assertFalse(mc.publicar_instagram("oi", ""))

    @patch.object(mc, "META_INSTAGRAM_ID", "ig1")
    @patch.object(mc, "META_ACCESS_TOKEN", "tok")
    def test_ok(self):
        self.mock_http.side_effect = [
            make_http_response(json_body={"id": "creation123"}),
            make_http_response(json_body={"id": "media999"}),
        ]
        self.assertTrue(mc.publicar_instagram("legenda", "http://img.jpg"))
        self.assertEqual(self.mock_http.call_count, 2)

    @patch.object(mc, "META_INSTAGRAM_ID", "ig1")
    @patch.object(mc, "META_ACCESS_TOKEN", "tok")
    def test_container_sem_id(self):
        self.mock_http.return_value = make_http_response(json_body={})
        self.assertFalse(mc.publicar_instagram("legenda", "http://img.jpg"))

    @patch.object(mc, "META_INSTAGRAM_ID", "ig1")
    @patch.object(mc, "META_ACCESS_TOKEN", "tok")
    def test_erro(self):
        self.mock_http.side_effect = Exception("boom")
        self.assertFalse(mc.publicar_instagram("legenda", "http://img.jpg"))


if __name__ == "__main__":
    unittest.main()
