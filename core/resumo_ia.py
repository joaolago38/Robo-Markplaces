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
    modelo: str | None = None,
    enriquecer_ml: bool | None = None,
    consolidado: dict[str, Any] | None = None,
    origem: str | None = None,
    exigir_contexto: bool = True,
    proposito: str | None = None,
    forcar_profundidade: str | None = None,
    forcar_modelo: bool = False,
    forcar_chamada: bool = False,
    temperature: float | None = None,
    system: str | None = None,
    somente_ia: bool = False,
) -> str:
    """
    Chama Claude com guardrail obrigatório. Nunca propaga exceção — retorna fallback.
    Se o prompt/contexto fala de Mercado Livre, injeta estado_ml e dosa profundidade.
    Sem contexto útil (padrão), não chama a API — preserva assertividade.
    `somente_ia=True` devolve string vazia se a API não responder (não mascara fallback).
    """
    if not (cfg.ANTHROPIC_API_KEY or "").strip():
        return "" if somente_ia else fallback

    def _falha() -> str:
        return "" if somente_ia else fallback

    try:
        from core.claude_client import contexto_suficiente

        ctx_obj: dict[str, Any] | str = contexto
        dosagem = None
        system_api = system
        usar_ml = enriquecer_ml
        if usar_ml is None:
            blob = f"{prompt} {contexto if isinstance(contexto, str) else json.dumps(contexto, ensure_ascii=False)}"
            usar_ml = "mercadolivre" in blob.lower() or "mercado livre" in blob.lower() or " ml " in f" {blob.lower()} "
        if usar_ml:
            try:
                from core.claude_contexto_ml import (
                    enriquecer_contexto_claude,
                    max_tokens_dosados,
                    system_com_decisao,
                )

                ctx_obj, dosagem = enriquecer_contexto_claude(
                    contexto if isinstance(contexto, dict) else {"contexto_texto": contexto},
                    consolidado=consolidado,
                    proposito=proposito or "sintese_ml",
                    forcar_profundidade=forcar_profundidade,
                )
                max_tokens = max_tokens_dosados(max_tokens, dosagem)
                prompt = (
                    f"{prompt}\n\nUse estado_ml e situacao_produto. "
                    f"Profundidade={dosagem.get('profundidade')}. "
                    "Priorize decisão (FAZER/NÃO FAZER/OBSERVAR)."
                )
                prompt = f"{system_com_decisao(system or '', dosagem)}\n\n{prompt}"
                system_api = dosagem.get("instrucoes") or system
            except Exception as exc:
                logger.warning("enriquecer_ml falhou: %s", exc)

        ctx_str = _contexto_json(ctx_obj)
        if exigir_contexto and not contexto_suficiente(ctx_str):
            logger.info("sintetizar_claude: contexto insuficiente — fallback (origem=%s)", origem or "?")
            return _falha()
        if proposito and not forcar_modelo:
            try:
                from core.claude_roteador import resolver_modelo_vendas

                rota = resolver_modelo_vendas(proposito=proposito)
                if rota.get("escalou"):
                    modelo = rota.get("modelo") or modelo
                    forcar_modelo = True
            except Exception as exc:
                logger.debug("roteamento claude: %s", exc)

        prompt_completo = f"{GUARDRAIL}\n\n{prompt}\n\n{GUARDRAIL}"
        resposta = perguntar(
            prompt_completo,
            max_tokens=max_tokens,
            contexto=ctx_str,
            modelo=modelo,
            origem=origem or "resumo_ia",
            exigir_contexto=exigir_contexto,
            forcar_modelo=forcar_modelo,
            forcar_chamada=forcar_chamada,
            temperature=temperature,
            system=system_api,
        )
        if not resposta or resposta.startswith("⚠️") or "API" in resposta:
            return _falha()
        return resposta.strip()
    except Exception as exc:
        logger.error("resumo_ia claude: %s", exc)
        return _falha()
