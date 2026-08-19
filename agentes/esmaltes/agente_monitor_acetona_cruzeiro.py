"""
agentes/esmaltes/agente_monitor_acetona_cruzeiro.py
Monitora Acetona Cruzeiro no ML: vendedores, margem média, manicures BR e estratégias Claude + Impala.

Catálogo: catalogo/acetona_cruzeiro_monitor.json

Uso:
  python -m agentes.esmaltes.agente_monitor_acetona_cruzeiro
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.catalogo_produtos import carregar_produtos_para_operacao
from core.claude_client import MODELO_RAPIDO, perguntar_estruturado
from core.config import (
    ACETONA_CRUZEIRO_ALERTA_COOLDOWN_SEG,
    ACETONA_CRUZEIRO_ALERTA_RESUMO,
    ACETONA_CRUZEIRO_CATALOGO,
    ACETONA_CRUZEIRO_MANICURES_CATALOGO,
    ACETONA_CRUZEIRO_PAUSA_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.esmaltes.analise_acetona_cruzeiro import (
    analisar_termo,
    carregar_manicures_brasil,
    consolidar_acetona,
    resumir_impala_para_claude,
)
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_acetona_cruzeiro")

HISTORY_PATH = ROOT / "logs" / "acetona_cruzeiro_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "acetona_cruzeiro_ultima.json"

_SCHEMA_ESTRATEGIA = {
    "type": "object",
    "properties": {
        "visao_mercado": {
            "type": "string",
            "description": "Parágrafo curto sobre o tamanho do mercado de acetona Cruzeiro vs oportunidade.",
        },
        "visao_manicures": {
            "type": "string",
            "description": "Como o universo de manicures no Brasil impacta a demanda (use só números do JSON).",
        },
        "estrategias": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "acao": {"type": "string"},
                    "prioridade": {"type": "string", "enum": ["alta", "media", "baixa"]},
                    "vinculo_impala": {"type": "string", "description": "SKU Impala ou ideia de bundle"},
                    "impacto_esperado": {"type": "string"},
                },
                "required": ["titulo", "acao", "prioridade"],
            },
        },
        "bundle_sugerido": {
            "type": "object",
            "properties": {
                "nome": {"type": "string"},
                "componentes": {"type": "array", "items": {"type": "string"}},
                "preco_sugerido_faixa": {"type": "string"},
                "justificativa": {"type": "string"},
            },
        },
    },
    "required": ["visao_mercado", "estrategias"],
}

_SYSTEM_ESTRATEGIA = (
    "Você é estrategista de e-commerce para manicures no Brasil. "
    "Com base APENAS nos dados JSON (mercado ML acetona Cruzeiro, catálogo Impala, referência manicures), "
    "defina estratégias para vender acetona Cruzeiro junto com kits Impala no Mercado Livre. "
    "Não invente preços, vendedores ou números fora do contexto. "
    "Priorize bundles, precificação, títulos de anúncio e cross-sell para salão/MEI."
)


def _carregar_itens() -> list[dict[str, Any]]:
    caminho = ROOT / ACETONA_CRUZEIRO_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        return [i for i in data if isinstance(i, dict) and i.get("ativo")]
    except Exception as exc:
        logger.error("Erro ao carregar catálogo acetona: %s", exc)
        return []


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _buscar_anuncios(item: dict[str, Any]) -> list[dict[str, Any]]:
    limite = int(item.get("limite_resultados") or 25)
    vistos: set[str] = set()
    saida: list[dict[str, Any]] = []
    termos = [str(item.get("termo_busca") or "").strip()]
    termos.extend(str(t) for t in (item.get("termos_alternativos") or []) if str(t).strip())
    for termo in termos:
        if not termo:
            continue
        for an in ml_client.buscar_concorrentes_por_termo(termo, limite=limite):
            iid = str(an.get("item_id") or "")
            if iid and iid in vistos:
                continue
            if iid:
                vistos.add(iid)
            saida.append(an)
    return saida


def _gerar_estrategias_claude(
    consolidado: dict[str, Any],
    manicures: dict[str, Any],
    impala: list[dict[str, Any]],
) -> dict[str, Any] | None:
    from core.claude_contexto_ml import (
        enriquecer_contexto_claude,
        max_tokens_dosados,
        system_com_decisao,
    )

    contexto = {
        "mercado_acetona_cruzeiro": consolidado,
        "manicures_brasil": manicures,
        "catalogo_impala_ativo": impala,
    }
    ctx, dosagem = enriquecer_contexto_claude(
        contexto,
        consolidado=consolidado,
        proposito="acetona_cruzeiro",
    )
    return perguntar_estruturado(
        (
            "Analise acetona Cruzeiro no ML cruzando produto × estado_ml. "
            f"Profundidade={dosagem.get('profundidade')}. "
            "Proponha estratégias Impala com foco em decisão "
            f"({', '.join((dosagem.get('foco_decisao') or [])[:3])})."
        ),
        _SCHEMA_ESTRATEGIA,
        "estrategia_acetona_impala",
        max_tokens=max_tokens_dosados(900, dosagem),
        contexto=json.dumps(ctx, ensure_ascii=False, indent=2),
        system=system_com_decisao(_SYSTEM_ESTRATEGIA, dosagem),
        modelo=MODELO_RAPIDO,
    )


def _montar_painel(
    consolidado: dict[str, Any],
    manicures: dict[str, Any],
    estrategias_ia: dict[str, Any] | None,
) -> str:
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente("monitor_acetona_cruzeiro", "🧴 *Acetona Cruzeiro — monitor ML completo*"),
        "",
        "*Mercado Cruzeiro (soma dos termos)*",
        f"  • Vendedores únicos: *{consolidado.get('vendedores_cruzeiro_unicos', 0)}*",
        f"  • Unidades vendidas (proxy): *{consolidado.get('unidades_vendidas_cruzeiro', 0)}*",
        f"  • Preço médio: {_fmt_brl(consolidado.get('preco_medio_cruzeiro'))}",
        f"  • Margem média estimada (seu custo × preço mercado): "
        f"{consolidado.get('margem_media_mercado_pct', 'n/d')}%",
        "",
        "*Manicures no Brasil (referência)*",
        f"  • MEI manicure/cabeleireiro (CNAE 9602-5/01): "
        f"*{manicures.get('mei_manicure_cabeleireiro', 'n/d'):,}*".replace(",", "."),
        f"  • Estabelecimentos ativos mesmo CNAE: "
        f"*{manicures.get('estabelecimentos_ativos_cnae_9602501', 'n/d'):,}*".replace(",", "."),
        f"  • Público ampliado salão+estética MEI: "
        f"*{manicures.get('publico_ampliado_salao_mei', 'n/d'):,}*".replace(",", "."),
        f"  • Endereçáveis ML (~{manicures.get('penetracao_ml_estimada_pct', 12)}%): "
        f"~*{manicures.get('manicures_enderecaveis_ml_estimado', 'n/d'):,}*".replace(",", "."),
        "",
    ]

    for r in consolidado.get("resultados") or []:
        linhas.append(
            f"*{r.get('nome', r.get('id'))}*: {r.get('vendedores_cruzeiro', 0)} vendedor(es) Cruzeiro | "
            f"média {_fmt_brl(r.get('preco_medio_cruzeiro'))} | "
            f"margem mercado {r.get('margem_media_mercado_pct', 'n/d')}%"
        )
        for d in (r.get("destaques_cruzeiro") or [])[:2]:
            titulo = str(d.get("titulo") or "")[:45]
            linhas.append(
                f"  • {titulo} — {_fmt_brl(d.get('preco'))} | {d.get('quantidade_vendida', 0)} vend."
            )
    linhas.append("")

    if estrategias_ia:
        if estrategias_ia.get("visao_mercado"):
            linhas.extend(["*Visão Claude — mercado*", estrategias_ia["visao_mercado"], ""])
        if estrategias_ia.get("visao_manicures"):
            linhas.extend(["*Visão Claude — manicures BR*", estrategias_ia["visao_manicures"], ""])
        bundle = estrategias_ia.get("bundle_sugerido") or {}
        if bundle.get("nome"):
            linhas.append(f"*Bundle sugerido:* {bundle.get('nome')} — {bundle.get('preco_sugerido_faixa', '')}")
            if bundle.get("justificativa"):
                linhas.append(f"  _{bundle['justificativa']}_")
            linhas.append("")
        for e in (estrategias_ia.get("estrategias") or [])[:5]:
            emoji = "🔴" if e.get("prioridade") == "alta" else "🟡"
            imp = f" (Impala: {e['vinculo_impala']})" if e.get("vinculo_impala") else ""
            linhas.append(f"  {emoji} *{e.get('titulo')}*{imp}")
            linhas.append(f"     {e.get('acao')}")

    return "\n".join(linhas).strip()


def _monitorar_item(item: dict[str, Any]) -> dict[str, Any]:
    anuncios = _buscar_anuncios(item)
    out = analisar_termo(item, anuncios)
    out["prioridade"] = int(item.get("prioridade") or 99)
    out["ok"] = out.get("ok", False)

    iid = str(item.get("id") or "")
    gauge("acetona.vendedores", float(out.get("vendedores_cruzeiro") or 0), tags=[f"termo:{iid}"])
    if out.get("margem_media_mercado_pct") is not None:
        gauge("acetona.margem_media_pct", float(out["margem_media_mercado_pct"]), tags=[f"termo:{iid}"])

    logger.info(
        "Acetona %s: %s vendedores Cruzeiro, margem média %s%%, preço médio %s",
        item.get("nome"),
        out.get("vendedores_cruzeiro"),
        out.get("margem_media_mercado_pct"),
        out.get("preco_medio_cruzeiro"),
    )
    return out


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — acetona Cruzeiro não alertará")

        itens = sorted(_carregar_itens(), key=lambda i: int(i.get("prioridade") or 99))
        if not itens:
            return {"ok": True, "total_itens": 0, "resultados": []}

        resultados: list[dict[str, Any]] = []
        for i, item in enumerate(itens):
            if i > 0 and ACETONA_CRUZEIRO_PAUSA_SEG > 0:
                time.sleep(ACETONA_CRUZEIRO_PAUSA_SEG)
            resultados.append(_monitorar_item(item))

        consolidado = consolidar_acetona(resultados)
        manicures = carregar_manicures_brasil(ACETONA_CRUZEIRO_MANICURES_CATALOGO)
        impala = resumir_impala_para_claude(carregar_produtos_para_operacao(merge_bling=False))
        estrategias_ia = _gerar_estrategias_claude(consolidado, manicures, impala)

        agora = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "timestamp": agora,
            "consolidado": consolidado,
            "manicures_brasil": manicures,
            "impala_resumo": impala,
            "estrategias_claude": estrategias_ia,
            "resultados": resultados,
        }
        escrever_json_atomico(SNAPSHOT_PATH, snapshot)

        historico = ler_json(HISTORY_PATH, default={})
        historico["ultima_varredura"] = agora
        historico["vendedores_cruzeiro"] = consolidado.get("vendedores_cruzeiro_unicos")
        historico["margem_media_pct"] = consolidado.get("margem_media_mercado_pct")
        historico["preco_medio"] = consolidado.get("preco_medio_cruzeiro")
        escrever_json_atomico(HISTORY_PATH, historico)

        gauge("acetona.vendedores_unicos", float(consolidado.get("vendedores_cruzeiro_unicos") or 0))
        try:
            from integracoes.esmaltes.metricas_sellers_mercado import emitir_sellers_mercado

            emitir_sellers_mercado(
                "cruzeiro.mercado",
                consolidado.get("anuncios_cruzeiro") or [],
                top_n=10,
            )
        except Exception as exc:
            logger.warning("metricas sellers cruzeiro: %s", exc)

        alerta_enviado = False
        if enviar_alerta and ACETONA_CRUZEIRO_ALERTA_RESUMO and consolidado.get("termos_com_dados"):
            painel = _montar_painel(consolidado, manicures, estrategias_ia)
            alerta_enviado = bool(
                alertar_gestor(
                    painel,
                    chave=chave_resumo_periodo("acetona:cruzeiro", horas_por_bucket=4),
                    cooldown_segundos=ACETONA_CRUZEIRO_ALERTA_COOLDOWN_SEG,
                    agente_id="monitor_acetona_cruzeiro",
                )
            )

        incrementar("acetona.rodadas", tags=[f"termos:{len(resultados)}"])
        return {
            "ok": True,
            "total_itens": len(resultados),
            "consolidado": consolidado,
            "estrategias_claude": estrategias_ia,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Monitor acetona Cruzeiro erro: %s", exc)
        incrementar("acetona.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor Acetona Cruzeiro ML")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Monitor Acetona Cruzeiro ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    c = out.get("consolidado") or {}
    logger.info(
        "Concluído: %s vendedores, margem média %s%%, alerta=%s",
        c.get("vendedores_cruzeiro_unicos"),
        c.get("margem_media_mercado_pct"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
