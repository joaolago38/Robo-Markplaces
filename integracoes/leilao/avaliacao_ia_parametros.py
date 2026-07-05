"""
integracoes/leilao/avaliacao_ia_parametros.py
Claude avalia parâmetros de leilão (env + catálogo) com base nos achados da rodada.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from core.claude_client import MODELO_RAPIDO, perguntar_estruturado
from core.config import (
    LEILAO_COMISSAO_PCT,
    LEILAO_LAUDO_BRL,
    LEILAO_MARGEM_FIPE_MIN_PCT,
    LEILAO_MARGEM_FIPE_MIN_REAIS,
    LEILAO_PRECO_MAX_LANCE,
    LEILAO_REMOCAO_ESTADIA_BRL,
    LEILAO_TAXA_ADMIN_BRL,
    LEILAO_TAXA_CADASTRO_BRL,
    SUMARE_LEILOES_LANCE_MIN_BRL,
)

logger = logging.getLogger("avaliacao_ia_leilao")

_SCHEMA_PARAMETROS = {
    "type": "object",
    "properties": {
        "resumo_situacao": {
            "type": "string",
            "description": "Parágrafo curto sobre a rodada e qualidade dos achados.",
        },
        "ajustes_parametros": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "parametro": {"type": "string", "description": "Nome do env ou campo do catálogo JSON."},
                    "escopo": {"type": "string", "enum": ["env", "catalogo_veiculo", "catalogo_sumare"]},
                    "valor_atual": {"type": "string"},
                    "valor_sugerido": {"type": "string"},
                    "motivo": {"type": "string"},
                    "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                },
                "required": ["parametro", "valor_sugerido", "motivo", "confianca"],
            },
        },
        "achados_revisar": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                    "motivo": {"type": "string"},
                },
                "required": ["titulo", "motivo", "confianca"],
            },
        },
        "alertas": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string"},
        },
    },
    "required": ["resumo_situacao", "ajustes_parametros"],
}

_SYSTEM = (
    "Você é analista de leilões de veículos recuperados (média monta / furto) no Brasil. "
    "Com base APENAS no JSON (parâmetros atuais, estatísticas da rodada e amostra de achados), "
    "sugira ajustes de parâmetros (margem FIPE mínima, teto de lance, taxas, lance mínimo Sumaré, "
    "termos_extra no catálogo). "
    "Não invente achados, preços FIPE ou URLs. "
    "Priorize sugestões acionáveis: se zero achados, considere afrouxar filtros; "
    "se muitos achados sem vantagem FIPE, considere ajustar margem ou taxas."
)


def parametros_env_leilao_veiculos() -> dict[str, Any]:
    return {
        "LEILAO_COMISSAO_PCT": LEILAO_COMISSAO_PCT,
        "LEILAO_TAXA_CADASTRO_BRL": LEILAO_TAXA_CADASTRO_BRL,
        "LEILAO_TAXA_ADMIN_BRL": LEILAO_TAXA_ADMIN_BRL,
        "LEILAO_REMOCAO_ESTADIA_BRL": LEILAO_REMOCAO_ESTADIA_BRL,
        "LEILAO_LAUDO_BRL": LEILAO_LAUDO_BRL,
        "LEILAO_PRECO_MAX_LANCE": LEILAO_PRECO_MAX_LANCE,
        "LEILAO_MARGEM_FIPE_MIN_PCT": LEILAO_MARGEM_FIPE_MIN_PCT,
        "LEILAO_MARGEM_FIPE_MIN_REAIS": LEILAO_MARGEM_FIPE_MIN_REAIS,
    }


def parametros_sumare(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "lance_minimo_brl": config.get("lance_minimo_brl", SUMARE_LEILOES_LANCE_MIN_BRL),
        "comitentes": config.get("comitentes"),
        "exigir_documento": config.get("exigir_documento", True),
        "excluir_sucata": config.get("excluir_sucata", True),
        "alertar_mudanca_lance": config.get("alertar_mudanca_lance", True),
    }


def _resumir_achado(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "titulo": str(item.get("titulo") or "")[:80],
        "marca": item.get("marca"),
        "modelo": item.get("modelo"),
        "ano": item.get("ano"),
        "lance_brl": item.get("lance_brl") or item.get("valor"),
        "valor_fipe": item.get("valor_fipe"),
        "margem_fipe_pct": item.get("margem_fipe_pct"),
        "margem_fipe_reais": item.get("margem_fipe_reais"),
        "vantajoso": item.get("vantajoso"),
        "fonte": item.get("fonte_nome") or item.get("fonte_id"),
        "uf": item.get("uf"),
    }


def _resumir_lote_sumare(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "numero_lote": item.get("numero_lote"),
        "titulo": str(item.get("titulo") or "")[:80],
        "lance_brl": item.get("lance_brl"),
        "comitente": item.get("comitente"),
        "tipo_comitente": item.get("tipo_comitente"),
        "cidade": item.get("cidade"),
        "uf": item.get("uf"),
    }


def _estatisticas_rodada_leilao(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    total_achados = sum(int(r.get("achados_total") or 0) for r in resultados)
    total_vantajosos = sum(int(r.get("vantajosos_total") or 0) for r in resultados)
    total_novos = sum(len(r.get("novos") or []) for r in resultados)
    return {
        "veiculos_monitorados": len(resultados),
        "achados_total": total_achados,
        "vantajosos_total": total_vantajosos,
        "novos_total": total_novos,
        "taxa_vantajoso_pct": round(100.0 * total_vantajosos / total_achados, 1) if total_achados else 0,
    }


def avaliar_parametros_leilao_veiculos(
    *,
    veiculos_catalogo: list[dict[str, Any]],
    resultados: list[dict[str, Any]],
    amostra_achados: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Sugere ajustes de parâmetros para o monitor FIPE de leilões."""
    amostra: list[dict[str, Any]] = []
    if amostra_achados:
        amostra = [_resumir_achado(a) for a in amostra_achados[:15]]
    else:
        for r in resultados:
            for item in (r.get("novos_vantajosos") or r.get("novos") or [])[:3]:
                amostra.append(_resumir_achado(item))
            if len(amostra) >= 15:
                break

    contexto = {
        "tipo": "leilao_veiculos_fipe",
        "parametros_env": parametros_env_leilao_veiculos(),
        "catalogo_veiculos": [
            {
                "id": v.get("id"),
                "marca": v.get("marca"),
                "modelo": v.get("modelo"),
                "perfil": v.get("perfil"),
                "prioridade": v.get("prioridade"),
                "termos_extra": v.get("termos_extra"),
                "ano_min": v.get("ano_min"),
                "ano_max": v.get("ano_max"),
            }
            for v in veiculos_catalogo
        ],
        "estatisticas_rodada": _estatisticas_rodada_leilao(resultados),
        "por_veiculo": [
            {
                "id": r.get("id"),
                "veiculo": r.get("veiculo"),
                "achados_total": r.get("achados_total"),
                "vantajosos_total": r.get("vantajosos_total"),
                "novos": len(r.get("novos") or []),
            }
            for r in resultados
        ],
        "amostra_achados": amostra,
    }
    return perguntar_estruturado(
        "Avalie os parâmetros do monitor de leilões de veículos e sugira ajustes.",
        _SCHEMA_PARAMETROS,
        "avaliacao_parametros_leilao",
        max_tokens=900,
        contexto=json.dumps(contexto, ensure_ascii=False, indent=2),
        system=_SYSTEM,
        modelo=MODELO_RAPIDO,
    )


def avaliar_parametros_sumare(
    *,
    config: dict[str, Any],
    lotes: list[dict[str, Any]],
    novos: list[dict[str, Any]],
    mudancas: list[dict[str, Any]],
    leiloes_encontrados: int,
) -> dict[str, Any] | None:
    contexto = {
        "tipo": "sumare_leiloes",
        "parametros_catalogo": parametros_sumare(config),
        "estatisticas_rodada": {
            "leiloes_encontrados": leiloes_encontrados,
            "lotes_veiculo_documento": len(lotes),
            "novos": len(novos),
            "mudancas_lance": len(mudancas),
            "lance_medio": round(
                sum(float(x.get("lance_brl") or 0) for x in lotes) / len(lotes), 2
            )
            if lotes
            else 0,
            "lance_minimo": min(float(x.get("lance_brl") or 0) for x in lotes) if lotes else None,
            "lance_maximo": max(float(x.get("lance_brl") or 0) for x in lotes) if lotes else None,
        },
        "amostra_lotes": [_resumir_lote_sumare(x) for x in lotes[:12]],
    }
    return perguntar_estruturado(
        "Avalie os parâmetros do monitor Sumaré Leilões (PREFEITURA/DETRAN) e sugira ajustes.",
        _SCHEMA_PARAMETROS,
        "avaliacao_parametros_sumare",
        max_tokens=800,
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
    for a in (ia.get("ajustes_parametros") or [])[:6]:
        conf = a.get("confianca", "media")
        emoji = "🟢" if conf == "alta" else "🟡" if conf == "media" else "⚪"
        atual = a.get("valor_atual")
        sug = a.get("valor_sugerido", "?")
        param = a.get("parametro", "?")
        escopo = a.get("escopo", "env")
        linha = f"  {emoji} *{param}* ({escopo})"
        if atual is not None:
            linha += f": {atual} → *{sug}*"
        else:
            linha += f": → *{sug}*"
        linhas.append(linha)
        if a.get("motivo"):
            linhas.append(f"     _{a['motivo']}_")
    for ar in (ia.get("achados_revisar") or [])[:3]:
        linhas.append(f"  🔍 {ar.get('titulo', '?')[:50]} — {ar.get('motivo', '')}")
    for alerta in (ia.get("alertas") or [])[:2]:
        linhas.append(f"  ⚠️ {alerta}")
    return "\n".join(linhas)
