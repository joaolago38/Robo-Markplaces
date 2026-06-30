"""Helpers HTTP compartilhados entre conftest e arquivos de teste."""
from __future__ import annotations

from unittest.mock import MagicMock


def make_http_response(*, status_code: int = 200, json_body: dict | None = None, text: str = "") -> MagicMock:
    """Response fake configurável (status, json, text)."""
    body = json_body if json_body is not None else {}
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or str(body)
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = RuntimeError(f"HTTP {status_code}")
    resp.json.return_value = body
    return resp
