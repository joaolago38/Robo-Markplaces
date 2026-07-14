"""
tests/conftest.py — fixtures compartilhadas para a suíte pytest.
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

# Clientes importam `request` por nome local; patchamos todos os bindings
# para que mock_http funcione independentemente de onde o teste importa.
_HTTP_REQUEST_PATHS = (
    "core.http_client.request",
    "integracoes.ml.ml_client.request",
    "integracoes.bling.bling_client.request",
    "integracoes.magalu.magalu_client.request",
    "integracoes.amazon.amazon_client.request",
    "integracoes.shopee.shopee_client.request",
    "integracoes.lojahub.lojahub_client.request",
    "integracoes.meta.meta_client.request",
)

_ENV_TOKEN_DEFAULTS = {
    "ML_ACCESS_TOKEN": "test-ml-token",
    "ML_SELLER_ID": "123456",
    "ML_CLIENT_ID": "test-ml-client-id",
    "ML_CLIENT_SECRET": "test-ml-client-secret",
    "ML_REFRESH_TOKEN": "test-ml-refresh",
    "BLING_ACCESS_TOKEN": "test-bling-token",
    "BLING_CLIENT_ID": "test-bling-client-id",
    "BLING_CLIENT_SECRET": "test-bling-client-secret",
    "BLING_REFRESH_TOKEN": "test-bling-refresh",
    "MAGALU_ACCESS_TOKEN": "test-magalu-token",
    "MAGALU_MERCHANT_ID": "test-magalu-merchant",
    "MAGALU_CLIENT_ID": "test-magalu-client-id",
    "MAGALU_CLIENT_SECRET": "test-magalu-client-secret",
    "SHOPEE_PARTNER_ID": "1",
    "SHOPEE_PARTNER_KEY": "test-shopee-key",
    "SHOPEE_SHOP_ID": "2",
    "SHOPEE_ACCESS_TOKEN": "test-shopee-token",
    "AMAZON_ACCESS_TOKEN": "test-amazon-token",
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "TELEGRAM_TOKEN": "test-telegram-token",
}


from tests.http_fixtures import make_http_response


@pytest.fixture(autouse=True)
def _reset_telegram_gate():
    """Evita vazamento de circuit breaker entre testes paralelos (xdist)."""
    from core import telegram_gate as tg

    tg.reset()
    yield
    tg.reset()


@pytest.fixture(autouse=True)
def _claude_ligado_nos_testes(tmp_path_factory):
    """
    Pausa operacional (CLAUDE_ATIVO=0 / logs/claude_toggle.json) não deve quebrar CI.
    Testes do próprio toggle usam patch próprio e sobrescrevem estes caminhos.
    """
    toggle = tmp_path_factory.mktemp("claude_toggle") / "claude_toggle.json"
    with ExitStack() as stack:
        stack.enter_context(patch("core.config.CLAUDE_ATIVO", True))
        stack.enter_context(patch("core.claude_toggle.TOGGLE_PATH", toggle))
        yield


@pytest.fixture
def mock_http():
    """
    Patch compartilhado de core.http_client.request (e re-exports nos clientes).
    Configure via mock_http.return_value ou mock_http.side_effect.
    """
    shared = MagicMock()
    shared.return_value = make_http_response()
    with ExitStack() as stack:
        for path in _HTTP_REQUEST_PATHS:
            stack.enter_context(patch(path, new=shared))
        yield shared


@pytest.fixture
def env_tokens(monkeypatch):
    """Tokens dummy no ambiente e em core.config para testes sem mock de cliente."""
    for key, value in _ENV_TOKEN_DEFAULTS.items():
        monkeypatch.setenv(key, value)

    import core.config as cfg

    cfg_patch = {k: v for k, v in _ENV_TOKEN_DEFAULTS.items() if hasattr(cfg, k)}
    with patch.multiple(cfg, **cfg_patch):
        yield _ENV_TOKEN_DEFAULTS
