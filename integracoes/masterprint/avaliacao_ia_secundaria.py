"""
integracoes/masterprint/avaliacao_ia_secundaria.py
Claude 1×/dia por agente Masterprint — análise concisa do ecossistema ML.

Política:
  - Recursos Claude limitados a UMA chamada/dia (BRT) por escopo (petg | escritorio).
  - Rodadas seguintes no mesmo dia reutilizam o cache da análise.
  - Reserva orçamento para esmaltes (piso de restante USD).
  - Falha/bloqueio NÃO impede o Telegram determinístico.
  - Não inventa custos/preços/vendas — só interpreta o JSON da rodada.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.claude_client import MODELO_RAPIDO, perguntar_estruturado
from core.config import (
    MASTERPRINT_CLAUDE_DIARIO,
    MASTERPRINT_CLAUDE_RESTANTE_MIN_USD,
    ROOT,
)
from core.horario import agora_brasil
from integracoes.masterprint.ramo import carregar_ramo

logger = logging.getLogger("avaliacao_ia_masterprint")

_USO_DIARIO_PATH = ROOT / "logs" / "masterprint_claude_diario.json"
_CACHE_PATH = ROOT / "logs" / "masterprint_claude_cache.json"

_SCHEMA = {
    "type": "object",
    "properties": {
        "ecosistema_ml": {
            "type": "string",
            "description": (
                "Parágrafo conciso (3-5 linhas) sobre o que os produtos Masterprint "
                "estão vivendo no ecossistema Mercado Livre nesta rodada."
            ),
        },
        "pressao_preco": {
            "type": "string",
            "description": "1 frase sobre pressão de preço / guerra de margem.",
        },
        "oportunidade": {
            "type": "string",
            "description": "1 frase com a melhor oportunidade observável nos dados.",
        },
        "acoes": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "prioridade": {"type": "string", "enum": ["alta", "media", "baixa"]},
                    "acao": {"type": "string"},
                    "motivo": {"type": "string"},
                },
                "required": ["prioridade", "acao", "motivo"],
            },
        },
        "alertas": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string"},
        },
    },
    "required": ["ecosistema_ml", "acoes"],
}

_SYSTEM = (
    "Você analisa o ecossistema Mercado Livre para produtos Masterprint "
    "(filamentos PETG e/ou material de escritório: pincéis recarregáveis e apagadores). "
    "O negócio de esmaltes/manicures é outro ramo (pode ser outro CNPJ/conta) e tem "
    "prioridade no orçamento de IA — esta análise é diária, curta e operacional. "
    "Com base APENAS no JSON: descreva o que esses produtos estão vivendo no ML "
    "(volume aparente, margem vs tabela, Δ vendas, pressão competitiva). "
    "Máximo 3 ações. NÃO invente custos, preços, vendas ou URLs. "
    "NÃO proponha campanhas que desviem foco/orçamento do ramo esmaltes."
)


def _hoje_brt() -> str:
    return agora_brasil().strftime("%Y-%m-%d")


def _carregar_uso() -> dict[str, Any]:
    data = ler_json(_USO_DIARIO_PATH, default={})
    return data if isinstance(data, dict) else {}


def _carregar_cache() -> dict[str, Any]:
    data = ler_json(_CACHE_PATH, default={})
    return data if isinstance(data, dict) else {}


def ja_usou_claude_hoje(escopo: str) -> bool:
    uso = _carregar_uso()
    return str(uso.get(escopo) or "") == _hoje_brt()


def cache_claude_hoje(escopo: str) -> dict[str, Any] | None:
    cache = _carregar_cache()
    bloco = cache.get(escopo)
    if not isinstance(bloco, dict):
        return None
    if str(bloco.get("data") or "") != _hoje_brt():
        return None
    ia = bloco.get("avaliacao_ia")
    return ia if isinstance(ia, dict) else None


def _marcar_uso_e_cache(escopo: str, ia: dict[str, Any]) -> None:
    hoje = _hoje_brt()
    uso = _carregar_uso()
    uso[escopo] = hoje
    uso["atualizado_em"] = agora_brasil().isoformat()
    escrever_json_atomico(_USO_DIARIO_PATH, uso)

    cache = _carregar_cache()
    cache[escopo] = {
        "data": hoje,
        "avaliacao_ia": ia,
        "gerado_em": agora_brasil().isoformat(),
    }
    escrever_json_atomico(_CACHE_PATH, cache)


def _pode_chamar_novo(escopo: str) -> tuple[bool, str]:
    if not MASTERPRINT_CLAUDE_DIARIO:
        return False, "MASTERPRINT_CLAUDE_DIARIO=0"
    if ja_usou_claude_hoje(escopo):
        return False, f"já usado hoje ({escopo})"
    try:
        from core.claude_orcamento import pode_chamar, resumo

        ok, motivo = pode_chamar()
        if not ok:
            return False, motivo
        r = resumo()
        restante = float(r.get("restante_usd") or 0)
        piso = float(MASTERPRINT_CLAUDE_RESTANTE_MIN_USD)
        if restante < piso:
            return (
                False,
                f"restante US$ {restante:.2f} < piso US$ {piso:.2f} (reserva esmaltes)",
            )
        return True, "ok"
    except Exception as exc:
        return False, f"gate Claude falhou: {exc}"


def _contexto_compacto(escopo: str, consolidado: dict[str, Any]) -> dict[str, Any]:
    ramo = carregar_ramo()

    def _mini(p: dict[str, Any]) -> dict[str, Any]:
        return {
            "titulo": str(p.get("titulo") or "")[:80],
            "preco": p.get("preco"),
            "custo": p.get("custo_unitario_brl"),
            "margem_brl": p.get("margem_brl"),
            "margem_pct": p.get("margem_pct"),
            "vendas": p.get("quantidade_vendida"),
            "lucro_proxy": p.get("lucro_proxy"),
            "delta_vendas": p.get("delta_vendas"),
            "tipo": p.get("tipo") or p.get("material"),
        }

    return {
        "escopo": escopo,
        "frequencia": "1x_por_dia",
        "ramo": {
            "nome_fantasia": ramo.get("nome_fantasia"),
            "cnpj": ramo.get("cnpj_formatado") or ramo.get("cnpj") or None,
            "ml_seller_id": ramo.get("ml_seller_id") or None,
            "ml_nickname": ramo.get("ml_nickname") or None,
            "conta_separada_esmaltes": ramo.get("conta_separada"),
        },
        "totais": {
            "anuncios": consolidado.get("total_anuncios_ativos"),
            "vendas": consolidado.get("vendas_totais"),
            "margem_media_brl": consolidado.get("margem_media_brl"),
            "lucro_proxy_total": consolidado.get("lucro_proxy_total"),
            "preco_min": consolidado.get("preco_min"),
            "preco_medio": consolidado.get("preco_medio"),
            "preco_max": consolidado.get("preco_max"),
            "por_tipo": consolidado.get("por_tipo"),
            "custo_padrao_1kg_brl": consolidado.get("custo_padrao_1kg_brl"),
            "custos_referencia": consolidado.get("custos_referencia"),
        },
        "mais_rentaveis": [_mini(p) for p in (consolidado.get("mais_rentaveis") or [])[:5]],
        "maior_ganho": [_mini(p) for p in (consolidado.get("maior_ganho") or [])[:5]],
        "mais_vendidos": [_mini(p) for p in (consolidado.get("mais_vendidos") or [])[:3]],
    }


def avaliar_masterprint_secundario(
    *,
    escopo: str,
    consolidado: dict[str, Any],
) -> dict[str, Any] | None:
    """
    1×/dia: gera análise. Mesmo dia: devolve cache.
    None se off / sem dados / orçamento / erro na 1ª chamada do dia.
    """
    cached = cache_claude_hoje(escopo)
    if cached is not None:
        logger.info("Claude Masterprint %s: reutilizando análise do dia", escopo)
        return {**cached, "_fonte": "cache_diario"}

    ok, motivo = _pode_chamar_novo(escopo)
    if not ok:
        logger.info("Claude Masterprint %s pulado: %s", escopo, motivo)
        return None
    if not consolidado or not consolidado.get("total_anuncios_ativos"):
        return None

    try:
        ctx = _contexto_compacto(escopo, consolidado)
        ia = perguntar_estruturado(
            (
                f"Análise diária concisa do ecossistema ML para Masterprint ({escopo}). "
                "O que estes produtos estão vivendo agora no Mercado Livre?"
            ),
            _SCHEMA,
            f"masterprint_diario_{escopo}",
            max_tokens=650,
            contexto=json.dumps(ctx, ensure_ascii=False, indent=2),
            system=_SYSTEM,
            modelo=MODELO_RAPIDO,
        )
        if isinstance(ia, dict) and ia:
            ia = {**ia, "_fonte": "nova_chamada_diaria", "_data": _hoje_brt()}
            _marcar_uso_e_cache(escopo, {k: v for k, v in ia.items() if not str(k).startswith("_")})
            return ia
        return None
    except Exception as exc:
        logger.warning("Claude Masterprint diário falhou (%s): %s", escopo, exc)
        return None


def formatar_secao_ia_masterprint(ia: dict[str, Any] | None) -> str:
    if not ia:
        return ""
    fonte = ia.get("_fonte") or ""
    tag_fonte = " _(cache do dia)_" if fonte == "cache_diario" else " _(1×/dia)_"
    linhas = [
        "",
        f"🤖 *Claude — ecossistema ML Masterprint*{tag_fonte}",
        "_Ramo secundário · orçamento IA prioriza esmaltes_",
        "",
    ]
    eco = ia.get("ecosistema_ml") or ia.get("resumo")
    if eco:
        linhas.extend([f"*O que está acontecendo:* {eco}", ""])
    if ia.get("pressao_preco"):
        linhas.append(f"*Pressão de preço:* {ia['pressao_preco']}")
    if ia.get("oportunidade"):
        linhas.append(f"*Oportunidade:* {ia['oportunidade']}")
    if ia.get("pressao_preco") or ia.get("oportunidade"):
        linhas.append("")
    for e in (ia.get("acoes") or [])[:3]:
        pri = str(e.get("prioridade") or "media")
        emoji = "🔴" if pri == "alta" else "🟡" if pri == "media" else "🟢"
        linhas.append(f"  {emoji} *{e.get('acao', '').strip()}*")
        if e.get("motivo"):
            linhas.append(f"     _{e['motivo']}_")
    for alerta in (ia.get("alertas") or [])[:3]:
        linhas.append(f"  ⚠️ {alerta}")
    return "\n".join(linhas)
