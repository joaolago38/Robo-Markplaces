"""
integracoes/esmaltes/avaliacao_ia_removedores.py
Claude sugere ajustes de termos de busca para removedores de unha no ML.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from core.claude_client import MODELO_RAPIDO, perguntar_estruturado

logger = logging.getLogger("avaliacao_ia_removedores")

_SCHEMA = {
    "type": "object",
    "properties": {
        "resumo_situacao": {
            "type": "string",
            "description": "Parágrafo sobre a rodada: cobertura, marcas líderes ou falta de dados.",
        },
        "segmentos": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "segmento_id": {"type": "string"},
                    "termo_busca_sugerido": {"type": "string"},
                    "termos_alternativos": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"type": "string"},
                    },
                    "motivo": {"type": "string"},
                    "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                },
                "required": ["segmento_id", "termo_busca_sugerido", "motivo", "confianca"],
            },
        },
        "ajustes_globais": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "parametro": {"type": "string"},
                    "valor_sugerido": {"type": "string"},
                    "motivo": {"type": "string"},
                },
                "required": ["parametro", "valor_sugerido", "motivo"],
            },
        },
        "alertas": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string"},
        },
    },
    "required": ["resumo_situacao", "segmentos"],
}

_SYSTEM = (
    "Você é analista de mercado de manicure no Mercado Livre Brasil. "
    "Com base APENAS no JSON (catálogo de termos, estatísticas da rodada e amostra de títulos), "
    "sugira termos de busca mais curtos e eficazes para encontrar removedores de unha/acetona. "
    "Prefira termos de 2-4 palavras que aparecem em títulos reais de anúncios ML "
    "(ex.: 'acetona cruzeiro', 'removedor impala', 'acetona manicure'). "
    "Evite termos longos com 'profissional' + 'manicure' + volume juntos. "
    "Se zero resultados: sugira termos mais genéricos. "
    "Não invente preços, vendas ou URLs."
)


def _resumir_segmento_catalogo(seg: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": seg.get("id"),
        "nome": seg.get("nome"),
        "termo_busca": seg.get("termo_busca"),
        "termos_alternativos": seg.get("termos_alternativos") or [],
    }


def avaliar_busca_removedores(
    *,
    catalogo: list[dict[str, Any]],
    consolidado: dict[str, Any],
    resultados: list[dict[str, Any]],
) -> dict[str, Any] | None:
    from core.claude_contexto_ml import (
        enriquecer_contexto_claude,
        max_tokens_dosados,
        system_com_decisao,
    )

    contexto = {
        "catalogo": [_resumir_segmento_catalogo(s) for s in catalogo],
        "consolidado": {
            "total_produtos_unicos": consolidado.get("total_produtos_unicos"),
            "total_vendas": consolidado.get("total_vendas"),
            "ranking_fabricantes": (consolidado.get("ranking_fabricantes") or [])[:6],
        },
        "por_segmento": [
            {
                "id": r.get("id"),
                "nome": r.get("nome"),
                "termo_busca": r.get("termo_busca"),
                "termo_usado": r.get("termo_usado"),
                "total_bruto": r.get("total_bruto"),
                "total_removedores": r.get("total_removedores"),
            }
            for r in resultados
        ],
        "amostra_titulos": [
            str(p.get("titulo") or "")[:80]
            for r in resultados
            for p in (r.get("produtos") or [])[:2]
        ][:12],
    }
    ctx, dosagem = enriquecer_contexto_claude(
        contexto,
        consolidado=consolidado,
        proposito="removedores_unha",
    )
    return perguntar_estruturado(
        (
            "Avalie a busca de removedores de unha no ML cruzando com estado_ml. "
            f"Profundidade={dosagem.get('profundidade')}. "
            "Sugira termos que favoreçam decisão de monitoramento."
        ),
        _SCHEMA,
        "avaliacao_busca_removedores",
        max_tokens=max_tokens_dosados(800, dosagem),
        contexto=json.dumps(ctx, ensure_ascii=False, indent=2),
        system=system_com_decisao(_SYSTEM, dosagem),
        modelo=MODELO_RAPIDO,
    )


def formatar_secao_ia(ia: dict[str, Any] | None) -> str:
    if not ia:
        return ""
    linhas = ["", "🤖 *Claude — busca removedores*", ""]
    if ia.get("resumo_situacao"):
        linhas.extend([str(ia["resumo_situacao"]), ""])
    for seg in (ia.get("segmentos") or [])[:6]:
        conf = seg.get("confianca", "media")
        emoji = "🟢" if conf == "alta" else "🟡"
        sid = seg.get("segmento_id", "?")
        linhas.append(f"  {emoji} *{sid}* → `{seg.get('termo_busca_sugerido', '')}`")
        alts = seg.get("termos_alternativos") or []
        if alts:
            linhas.append(f"     alt: {', '.join(f'`{a}`' for a in alts[:3])}")
        if seg.get("motivo"):
            linhas.append(f"     _{seg['motivo']}_")
    for a in (ia.get("ajustes_globais") or [])[:3]:
        linhas.append(f"  ⚙️ *{a.get('parametro')}*: {a.get('valor_sugerido')}")
        if a.get("motivo"):
            linhas.append(f"     _{a['motivo']}_")
    for alerta in (ia.get("alertas") or [])[:3]:
        linhas.append(f"  ⚠️ {alerta}")
    return "\n".join(linhas)
