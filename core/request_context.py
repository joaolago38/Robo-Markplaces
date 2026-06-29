"""
core/request_context.py
Correlation ID por requisição/operação — permite agrupar, no Log
Explorer do Datadog, todas as linhas de log geradas durante uma mesma
chamada HTTP da API (ou execução de um agente), filtrando por
`request_id:<id>`.

Usa contextvars (não thread-local puro) para funcionar corretamente
com o Flask de forma simples no modelo de execução síncrono atual.
"""
from __future__ import annotations

import contextvars
import uuid

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def novo_request_id() -> str:
    """Gera um id curto e legível para correlacionar logs de uma operação."""
    return uuid.uuid4().hex[:12]


def definir_request_id(valor: str | None) -> None:
    _request_id_var.set(valor)


def obter_request_id() -> str | None:
    return _request_id_var.get()
