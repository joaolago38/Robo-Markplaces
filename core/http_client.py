"""
core/http_client.py
Cliente HTTP compartilhado com retry e backoff para falhas transitórias.
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("http_client")

_RETRY = Retry(
    total=3,
    connect=3,
    read=3,
    status=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"}),
    raise_on_status=False,
)
_ADAPTER = HTTPAdapter(max_retries=_RETRY)
_SESSION = requests.Session()
_SESSION.mount("http://", _ADAPTER)
_SESSION.mount("https://", _ADAPTER)


def request(method: str, url: str, timeout: int = 15, **kwargs: Any) -> requests.Response:
    """
    Executa request com sessão compartilhada + política de retry.
    """
    response = _SESSION.request(method=method, url=url, timeout=timeout, **kwargs)
    return response
