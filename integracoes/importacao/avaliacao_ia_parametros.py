"""
integracoes/importacao/avaliacao_ia_parametros.py
Claude avalia parâmetros de importação Alibaba (catálogo + env) com base na rodada.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from core.claude_client import MODELO_RAPIDO, perguntar_estruturado
from core.config import (
    ALIBABA_MARGEM_MIN_PCT,
    ALIBABA_MARGEM_MIN_REAIS,
    CAMBIO_ALERTA_VARIACAO_PCT,
    IMPORTACAO_FRETE_AEREO_USD_KG,
    IMPORTACAO_FRETE_MARITIMO_USD_KG,
    IMPORTACAO_II_PCT_DEFAULT,
)

logger = logging.getLogger("avaliacao_ia_alibaba")

_SCHEMA_PARAMETROS = {
    "type": "object",
    "properties": {
        "resumo_situacao": {
            "type": "string",
            "description": "Parágrafo sobre oportunidades, câmbio e margens da rodada.",
        },
        "produtos": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "produto_id": {"type": "string"},
                    "parametros_sugeridos": {
                        "type": "object",
                        "properties": {
                            "preco_max_usd": {"type": "number"},
                            "moq_max": {"type": "integer"},
                            "margem_minima_pct": {"type": "number"},
                            "margem_minima_reais": {"type": "number"},
                            "frete_preferido": {"type": "string", "enum": ["maritimo", "aereo", "indiferente"]},
                            "termo_busca": {"type": "string"},
                        },
                    },
                    "motivo": {"type": "string"},
                    "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                },
                "required": ["produto_id", "motivo", "confianca"],
            },
        },
        "ajustes_globais": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "parametro": {"type": "string"},
                    "valor_atual": {"type": "string"},
                    "valor_sugerido": {"type": "string"},
                    "motivo": {"type": "string"},
                },
                "required": ["parametro", "valor_sugerido", "motivo"],
            },
        },
        "riscos": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string"},
        },
    },
    "required": ["resumo_situacao", "produtos"],
}

_SYSTEM = (
    "Você é analista de importação China→Brasil (Alibaba) para e-commerce no Mercado Livre. "
    "Com base APENAS no JSON (parâmetros atuais, câmbio, análises de margem e oportunidades), "
    "sugira ajustes de preco_max_usd, moq_max, margem mínima, frete preferido e termos de busca "
    "por produto no catálogo. "
    "Não invente preços FOB, cotações ou fornecedores. "
    "Se nenhuma oportunidade lucrativa: sugira afrouxar preco_max_usd ou revisar MOQ; "
    "se câmbio subiu muito: alerte impacto no landed cost."
)


def parametros_globais_alibaba() -> dict[str, Any]:
    return {
        "ALIBABA_MARGEM_MIN_PCT": ALIBABA_MARGEM_MIN_PCT,
        "ALIBABA_MARGEM_MIN_REAIS": ALIBABA_MARGEM_MIN_REAIS,
        "CAMBIO_ALERTA_VARIACAO_PCT": CAMBIO_ALERTA_VARIACAO_PCT,
        "IMPORTACAO_II_PCT_DEFAULT": IMPORTACAO_II_PCT_DEFAULT,
        "IMPORTACAO_FRETE_MARITIMO_USD_KG": IMPORTACAO_FRETE_MARITIMO_USD_KG,
        "IMPORTACAO_FRETE_AEREO_USD_KG": IMPORTACAO_FRETE_AEREO_USD_KG,
    }


def _resumir_produto_catalogo(produto: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": produto.get("id"),
        "nome": produto.get("nome"),
        "preco_max_usd": produto.get("preco_max_usd"),
        "moq_max": produto.get("moq_max"),
        "margem_minima_pct": produto.get("margem_minima_pct"),
        "margem_minima_reais": produto.get("margem_minima_reais"),
        "termo_busca": produto.get("termo_busca"),
        "ncm": produto.get("ncm"),
        "ii_pct": produto.get("ii_pct"),
        "peso_kg_unitario": produto.get("peso_kg_unitario"),
    }


def _resumir_resultado_busca(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r.get("id"),
        "produto": r.get("produto"),
        "oportunidades_total": r.get("oportunidades_total"),
        "novos": len(r.get("novos") or []),
    }


def _resumir_resultado_inteligencia(r: dict[str, Any]) -> dict[str, Any]:
    mk = r.get("precos_marketplace") or {}
    melhor = r.get("melhor_analise") or {}
    mm = melhor.get("margem_melhor") or {}
    return {
        "id": r.get("id"),
        "produto": r.get("produto"),
        "total_oportunidades": r.get("total_oportunidades"),
        "lucrativas": r.get("lucrativas"),
        "preco_mediana_ml_brl": mk.get("preco_mediana_brl"),
        "total_anuncios_ml": mk.get("total_anuncios"),
        "melhor_fob_usd": melhor.get("preco_usd"),
        "melhor_moq": melhor.get("moq"),
        "melhor_margem_pct": mm.get("margem_pct"),
        "melhor_margem_brl": mm.get("margem_brl"),
        "lucro_razoavel": melhor.get("lucro_razoavel"),
        "melhor_frete": melhor.get("melhor_frete"),
    }


def avaliar_parametros_alibaba_busca(
    *,
    produtos_catalogo: list[dict[str, Any]],
    resultados: list[dict[str, Any]],
) -> dict[str, Any] | None:
    contexto = {
        "tipo": "alibaba_busca_simples",
        "parametros_globais": parametros_globais_alibaba(),
        "catalogo": [_resumir_produto_catalogo(p) for p in produtos_catalogo],
        "estatisticas": {
            "produtos": len(resultados),
            "oportunidades_total": sum(int(r.get("oportunidades_total") or 0) for r in resultados),
            "novos_total": sum(len(r.get("novos") or []) for r in resultados),
        },
        "por_produto": [_resumir_resultado_busca(r) for r in resultados],
        "amostra_novos": [
            {
                "produto_id": r.get("id"),
                "titulo": str(n.get("titulo") or "")[:70],
                "preco_usd": n.get("preco_usd"),
                "moq": n.get("moq"),
            }
            for r in resultados
            for n in (r.get("novos") or [])[:2]
        ][:10],
    }
    return perguntar_estruturado(
        "Avalie parâmetros de busca Alibaba e sugira ajustes no catálogo.",
        _SCHEMA_PARAMETROS,
        "avaliacao_parametros_alibaba",
        max_tokens=900,
        contexto=json.dumps(contexto, ensure_ascii=False, indent=2),
        system=_SYSTEM,
        modelo=MODELO_RAPIDO,
    )


def avaliar_parametros_alibaba_inteligencia(
    *,
    produtos_catalogo: list[dict[str, Any]],
    resultados: list[dict[str, Any]],
    cotacao: dict[str, Any],
    variacao_cambio: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    contexto = {
        "tipo": "alibaba_inteligencia_margem",
        "parametros_globais": parametros_globais_alibaba(),
        "cotacao_usd_brl": cotacao.get("usd_brl"),
        "variacao_cambio": variacao_cambio,
        "catalogo": [_resumir_produto_catalogo(p) for p in produtos_catalogo],
        "estatisticas": {
            "produtos": len(resultados),
            "lucrativas_total": sum(int(r.get("lucrativas") or 0) for r in resultados),
            "oportunidades_total": sum(int(r.get("total_oportunidades") or 0) for r in resultados),
        },
        "por_produto": [_resumir_resultado_inteligencia(r) for r in resultados],
    }
    return perguntar_estruturado(
        "Avalie parâmetros de importação Alibaba (custo landed + margem ML) e sugira ajustes.",
        _SCHEMA_PARAMETROS,
        "avaliacao_parametros_alibaba_margem",
        max_tokens=900,
        contexto=json.dumps(contexto, ensure_ascii=False, indent=2),
        system=_SYSTEM,
        modelo=MODELO_RAPIDO,
    )


def formatar_secao_ia(ia: dict[str, Any] | None) -> str:
    if not ia:
        return ""
    linhas = ["", "🤖 *Claude — parâmetros sugeridos*", ""]
    if ia.get("resumo_situacao"):
        linhas.extend([str(ia["resumo_situacao"]), ""])
    for p in (ia.get("produtos") or [])[:5]:
        conf = p.get("confianca", "media")
        emoji = "🟢" if conf == "alta" else "🟡"
        pid = p.get("produto_id", "?")
        linhas.append(f"  {emoji} *{pid}*")
        params = p.get("parametros_sugeridos") or {}
        partes = []
        for chave in ("preco_max_usd", "moq_max", "margem_minima_pct", "frete_preferido", "termo_busca"):
            if params.get(chave) is not None:
                partes.append(f"{chave}={params[chave]}")
        if partes:
            linhas.append(f"     → {', '.join(partes)}")
        if p.get("motivo"):
            linhas.append(f"     _{p['motivo']}_")
    for a in (ia.get("ajustes_globais") or [])[:4]:
        linhas.append(
            f"  ⚙️ *{a.get('parametro')}*: {a.get('valor_atual', '?')} → *{a.get('valor_sugerido')}*"
        )
        if a.get("motivo"):
            linhas.append(f"     _{a['motivo']}_")
    for risco in (ia.get("riscos") or [])[:3]:
        linhas.append(f"  ⚠️ {risco}")
    return "\n".join(linhas)
