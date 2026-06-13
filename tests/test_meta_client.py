"""
tests/test_meta_client.py
Cobre publicar_facebook e publicar_instagram (todos os ramos).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integracoes.meta import meta_client as mc


def _resp(body: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = body or {}
    return r


class TestPublicarFacebook(unittest.TestCase):
    @patch.object(mc, "META_PAGE_ID", "")
    @patch.object(mc, "META_ACCESS_TOKEN", "")
    def test_sem_config(self, *_):
        self.assertFalse(mc.publicar_facebook("oi"))

    @patch.object(mc, "META_PAGE_ID", "page1")
    @patch.object(mc, "META_ACCESS_TOKEN", "tok")
    @patch.object(mc, "request")
    def test_ok(self, mock_request, *_):
        mock_request.return_value = _resp({"id": "post1"})
        self.assertTrue(mc.publicar_facebook("oi"))

    @patch.object(mc, "META_PAGE_ID", "page1")
    @patch.object(mc, "META_ACCESS_TOKEN", "tok")
    @patch.object(mc, "request", side_effect=Exception("boom"))
    def test_erro(self, *_):
        self.assertFalse(mc.publicar_facebook("oi"))


class TestPublicarInstagram(unittest.TestCase):
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
    @patch.object(mc, "request")
    def test_ok(self, mock_request, *_):
        mock_request.side_effect = [_resp({"id": "creation123"}), _resp({"id": "media999"})]
        self.assertTrue(mc.publicar_instagram("legenda", "http://img.jpg"))
        self.assertEqual(mock_request.call_count, 2)

    @patch.object(mc, "META_INSTAGRAM_ID", "ig1")
    @patch.object(mc, "META_ACCESS_TOKEN", "tok")
    @patch.object(mc, "request")
    def test_container_sem_id(self, mock_request, *_):
        mock_request.return_value = _resp({})  # sem 'id'
        self.assertFalse(mc.publicar_instagram("legenda", "http://img.jpg"))

    @patch.object(mc, "META_INSTAGRAM_ID", "ig1")
    @patch.object(mc, "META_ACCESS_TOKEN", "tok")
    @patch.object(mc, "request", side_effect=Exception("boom"))
    def test_erro(self, *_):
        self.assertFalse(mc.publicar_instagram("legenda", "http://img.jpg"))


if __name__ == "__main__":
    unittest.main()
