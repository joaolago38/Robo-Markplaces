"""
core/claude_contexto_ml.py
Facade estável para análises Claude × Mercado Livre.

Delegação: core.claude_ml (estado / stress / dosagem / enriquecedor).
"""
from __future__ import annotations

from core.claude_ml.dosagem import (
    PROFUNDIDADE_TOKENS as _PROFUNDIDADE_TOKENS,
    SYSTEM_DECISAO as _SYSTEM_DECISAO,
    dosar_analise_para_decisao,
    max_tokens_dosados,
    system_com_decisao,
)
from core.claude_ml.enriquecedor import enriquecer_contexto_claude
from core.claude_ml.estado import _snapshot  # noqa: F401 — reexport p/ testes
from core.claude_ml.estado import carregar_estado_ml
from core.claude_ml.numeros import cfg_bool as _cfg_bool
from core.claude_ml.numeros import num as _num
from core.claude_ml.numeros import primeiro_num as _primeiro_num
from core.claude_ml.stress import stress_produto

__all__ = [
    "carregar_estado_ml",
    "stress_produto",
    "dosar_analise_para_decisao",
    "max_tokens_dosados",
    "enriquecer_contexto_claude",
    "system_com_decisao",
    "_SYSTEM_DECISAO",
    "_PROFUNDIDADE_TOKENS",
    "_cfg_bool",
    "_num",
    "_primeiro_num",
]
