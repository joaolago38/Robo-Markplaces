"""
core/resumo_ia.py
Camada compartilhada para sínteses via Claude com fallback seguro.

Escolha de módulo centralizado (em vez de duplicar em cada agente): operacao_24h,
notificador, repricing e monitor de concorrentes seguem o mesmo contrato validado
em agentes/panorama/agente_panorama.py::_sintetizar_claude().
"""
from __future__ import annotations

import json
import logging
from typing import Any

import core.config as cfg
from core.claude_client import perguntar

logger = logging.getLogger("resumo_ia")

GUARDRAIL = (
    "Use apenas os dados presentes no contexto fornecido. "
    "Nunca invente números, preços ou fatos que não estejam explicitamente no JSON."
)


def _contexto_json(contexto: dict[str, Any] | str) -> str:
    if isinstance(contexto, str):
        return contexto
    return json.dumps(contexto, ensure_ascii=False, indent=2)


def sintetizar_claude(
    prompt: str,
    contexto: dict[str, Any] | str,
    fallback: str,
    *,
    max_tokens: int = 500,
) -> str:
    """
    Chama Claude com guardrail obrigatório. Nunca propaga exceção — retorna fallback.
    """
    if not (cfg.ANTHROPIC_API_KEY or "").strip():
        return fallback

    try:
        ctx_str = _contexto_json(contexto)
        prompt_completo = f"{GUARDRAIL}\n\n{prompt}\n\n{GUARDRAIL}"
        resposta = perguntar(prompt_completo, max_tokens=max_tokens, contexto=ctx_str)
        if not resposta or resposta.startswith("⚠️") or "API" in resposta:
            return fallback
        return resposta.strip()
    except Exception as exc:
        logger.error("resumo_ia claude: %s", exc)
        return fallback
