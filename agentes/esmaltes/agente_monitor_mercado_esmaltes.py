"""
agentes/esmaltes/agente_monitor_mercado_esmaltes.py
Monitora o mercado de esmaltes no ML: cores, formato dos kits, margem viável e propostas de competição.

Catálogo: catalogo/esmaltes_mercado_segmentos.json
Custos/referência: catalogo/produtos.json (sku_referencia por segmento)

Uso:
  python -m agentes.esmaltes.agente_monitor_mercado_esmaltes
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.catalogo_produtos import carregar_produtos_para_operacao
from core.config import (
    ESMALTES_MERCADO_ABAIXO_CONCORRENTE_PCT,
    ESMALTES_MERCADO_ALERTA_COOLDOWN_SEG,
    ESMALTES_MERCADO_ALERTA_RESUMO,
    ESMALTES_MERCADO_CATALOGO,
    ESMALTES_MERCADO_PAUSA_SEG,
    ESMALTES_MERCADO_VENDAS_MIN,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.esmaltes.analise_mercado import analisar_segmento, consolidar_mercado
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_mercado_esmaltes")

HISTORY_PATH = ROOT / "logs" / "esmaltes_mercado_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "esmaltes_mercado_ultima.json"


def _carregar_segmentos() -> list[dict[str, Any]]:
    caminho = ROOT / ESMALTES_MERCADO_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        return [s for s in data if isinstance(s, dict) and s.get("ativo")]
    except Exception as exc:
        logger.error("Erro ao carregar catálogo mercado esmaltes: %s", exc)
        return []


def _mapa_produtos() -> dict[str, dict[str, Any]]:
    produtos = carregar_produtos_para_operacao(merge_bling=False)
    return {str(p.get("sku") or ""): p for p in produtos if p.get("sku")}


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _montar_secao_segmento(seg: dict[str, Any]) -> list[str]:
    linhas = [f"*{seg.get('nome', seg.get('id', '?'))}* ({seg.get('total_anuncios', 0)} anúncios)"]

    kits = seg.get("padroes_kits") or []
    if kits:
        k = kits[0]
        linhas.append(
            f"  Kit líder: {k['qtd']} un | {k['vendidos']} vend. | média {_fmt_brl(k.get('preco_medio'))}"
        )

    cores = seg.get("tendencia_cores") or []
    if cores:
        linhas.append("  Cores: " + ", ".join(c["cor"] for c in cores[:4]))

    for dest in (seg.get("destaques") or [])[:2]:
        titulo = str(dest.get("titulo") or "")[:50]
        linhas.append(
            f"  • {titulo} — {_fmt_brl(dest.get('preco'))} | "
            f"{dest.get('quantidade_vendida', 0)} vend. | {dest.get('descricao_kit', '')}"
        )
    return linhas


def _montar_painel(resultados: list[dict[str, Any]], consolidado: dict[str, Any]) -> str:
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente("monitor_mercado_esmaltes", "💄 *Mercado esmaltes ML — visão competitiva*"),
        "",
        f"_{consolidado.get('total_anuncios_unicos', 0)} anúncios únicos em "
        f"{consolidado.get('total_segmentos', 0)} segmentos | "
        f"{consolidado.get('total_oportunidades_margem', 0)} oportunidade(s) com margem viável_",
        "",
    ]

    ranking = consolidado.get("ranking_marcas_global") or []
    if ranking:
        linhas.append("*Marcas que mais vendem:*")
        for item in ranking[:5]:
            linhas.append(f"  • {item['marca']}: {item['vendidos']} vendas")
        linhas.append("")

    propostas = [p for p in (consolidado.get("propostas") or []) if p.get("prioridade") == "alta"]
    media = [p for p in (consolidado.get("propostas") or []) if p.get("prioridade") == "media"]

    linhas.append("🎯 *Como competir (margem satisfatória)*")
    if propostas:
        for p in propostas[:8]:
            linhas.append(f"  • {p.get('texto', '')}")
    else:
        linhas.append("  _Nenhuma ação de preço urgente — veja tendências abaixo._")
    linhas.append("")

    if media:
        linhas.append("📌 *Tendências (kits e cores)*")
        for p in media[:6]:
            linhas.append(f"  • {p.get('texto', '')}")
        linhas.append("")

    linhas.append("🔎 *Por segmento*")
    for seg in sorted(resultados, key=lambda x: int(x.get("prioridade") or 99))[:6]:
        if not seg.get("ok"):
            continue
        linhas.extend(_montar_secao_segmento(seg))
        linhas.append("")

    return "\n".join(linhas).strip()


def _monitorar_segmento(
    segmento: dict[str, Any],
    produtos_por_sku: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    termo = str(segmento.get("termo_busca") or "").strip()
    limite = int(segmento.get("limite_resultados") or 20)
    if not termo:
        return {"id": segmento.get("id"), "ok": False, "motivo": "termo vazio"}

    anuncios = ml_client.buscar_concorrentes_por_termo(termo, limite=limite)
    analise = analisar_segmento(
        segmento,
        anuncios,
        produtos_por_sku,
        vendas_min=ESMALTES_MERCADO_VENDAS_MIN,
        abaixo_concorrente_pct=ESMALTES_MERCADO_ABAIXO_CONCORRENTE_PCT,
    )

    sid = str(segmento.get("id") or "")
    gauge("esmaltes.mercado.anuncios", float(len(anuncios)), tags=[f"segmento:{sid}"])
    gauge(
        "esmaltes.mercado.oportunidades",
        float(len(analise.get("oportunidades_margem") or [])),
        tags=[f"segmento:{sid}"],
    )

    logger.info(
        "Mercado esmaltes %s: %s anúncio(s), %s oportunidade(s), %s proposta(s)",
        segmento.get("nome"),
        len(anuncios),
        len(analise.get("oportunidades_margem") or []),
        len(analise.get("propostas") or []),
    )
    return analise


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas mercado esmaltes não serão entregues")

        segmentos = sorted(_carregar_segmentos(), key=lambda s: int(s.get("prioridade") or 99))
        if not segmentos:
            return {"ok": True, "total_segmentos": 0, "resultados": [], "consolidado": {}}

        produtos_por_sku = _mapa_produtos()
        resultados: list[dict[str, Any]] = []
        agora = datetime.now(timezone.utc).isoformat()

        for i, segmento in enumerate(segmentos):
            if i > 0 and ESMALTES_MERCADO_PAUSA_SEG > 0:
                time.sleep(ESMALTES_MERCADO_PAUSA_SEG)
            resultados.append(_monitorar_segmento(segmento, produtos_por_sku))

        consolidado = consolidar_mercado(resultados)

        snapshot = {
            "timestamp": agora,
            "consolidado": consolidado,
            "segmentos": [
                {
                    "id": r.get("id"),
                    "nome": r.get("nome"),
                    "total_anuncios": r.get("total_anuncios"),
                    "oportunidades": len(r.get("oportunidades_margem") or []),
                    "propostas": r.get("propostas"),
                }
                for r in resultados
                if r.get("ok")
            ],
        }
        escrever_json_atomico(SNAPSHOT_PATH, snapshot)

        historico = ler_json(HISTORY_PATH, default={})
        historico["ultima_varredura"] = agora
        historico["total_anuncios_unicos"] = consolidado.get("total_anuncios_unicos")
        historico["total_oportunidades"] = consolidado.get("total_oportunidades_margem")
        historico["propostas_alta"] = len(
            [p for p in (consolidado.get("propostas") or []) if p.get("prioridade") == "alta"]
        )
        escrever_json_atomico(HISTORY_PATH, historico)

        alerta_enviado = False
        if enviar_alerta and ESMALTES_MERCADO_ALERTA_RESUMO and resultados:
            painel = _montar_painel(resultados, consolidado)
            alerta_enviado = bool(
                alertar_gestor(
                    painel,
                    chave=chave_resumo_periodo("esmaltes:mercado", horas_por_bucket=4),
                    cooldown_segundos=ESMALTES_MERCADO_ALERTA_COOLDOWN_SEG,
                    agente_id="monitor_mercado_esmaltes",
                )
            )

        incrementar("esmaltes.mercado.rodadas", tags=[f"segmentos:{len(resultados)}"])
        return {
            "ok": True,
            "total_segmentos": len(resultados),
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
            "consolidado": consolidado,
            "snapshot": str(SNAPSHOT_PATH),
        }
    except Exception as exc:
        logger.error("Agente mercado esmaltes erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor mercado esmaltes ML")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Monitor mercado esmaltes ML ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    logger.info(
        "Concluído: %s segmento(s), %s anúncios únicos, alerta=%s",
        out.get("total_segmentos"),
        (out.get("consolidado") or {}).get("total_anuncios_unicos"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
