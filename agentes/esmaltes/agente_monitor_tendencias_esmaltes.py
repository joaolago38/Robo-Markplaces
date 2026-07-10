"""
agentes/esmaltes/agente_monitor_tendencias_esmaltes.py
Monitora tendências de esmaltes na internet e cruza com marketplaces (ML, Magalu, Shopee, Amazon).

Catálogo: catalogo/esmaltes_tendencias_internet.json

Uso:
  python -m agentes.esmaltes.agente_monitor_tendencias_esmaltes
  python -m agentes.esmaltes.agente_monitor_tendencias_esmaltes --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    ESMALTES_TENDENCIAS_ALERTA_COOLDOWN_SEG,
    ESMALTES_TENDENCIAS_ALERTA_RESUMO,
    ESMALTES_TENDENCIAS_CATALOGO,
    ESMALTES_TENDENCIAS_PAUSA_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.graficos import grafico_evolucao
from core.notificador import alertar_gestor, chave_resumo_periodo, enviar_foto_gestor
from core.prontidao import pode_alertar_esmaltes
from core.series_historica import formatar_comparativo, registrar_ponto
from integracoes.esmaltes.cruzamento_tendencias_mercado import consolidar_varredura, processar_segmento
from integracoes.marketplaces.busca_multi_marketplace import resolver_fn_busca_esmaltes

logger = logging.getLogger("agente_monitor_tendencias_esmaltes")

SNAPSHOT_PATH = ROOT / "logs" / "esmaltes_tendencias_ultima.json"
HISTORY_PATH = ROOT / "logs" / "esmaltes_tendencias_history.json"
SERIES_PATH = ROOT / "logs" / "esmaltes_tendencias_series.json"
GRAFICO_PATH = ROOT / "logs" / "esmaltes_tendencias_grafico.png"

_SERIES_CAMPOS = [
    ("total_web_hits", "Hits web"),
    ("total_anuncios_mp", "Anúncios MP"),
    ("oportunidades", "Oportunidades"),
    ("confirmadas", "Confirmadas"),
]

_STATUS_LABEL = {
    "oportunidade": "🚀 Oportunidade (web quente, MP frio)",
    "confirmada": "✅ Confirmada (web + MP)",
    "emergente": "📈 Emergente",
    "saturada_mp": "📦 Saturada no MP",
    "fraca": "— Fraca",
}


def diagnosticar_fontes_vazias(resultados: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Detecta varredura sem nenhum hit web nem anúncio MP em todos os segmentos.
    Isso indica falha de coleta, não ausência de tendências no mercado.
    """
    ok = [r for r in resultados if r.get("ok")]
    if not ok:
        return None

    total_web = sum(int(r.get("total_web_hits") or 0) for r in ok)
    total_mp = sum(int(r.get("total_anuncios_mp") or 0) for r in ok)
    if total_web > 0 or total_mp > 0:
        return None

    from core.ddg_lite import mensagem_circuit_breaker
    from core.prontidao import brave_configurado, ml_configurado

    dicas: list[str] = []
    if brave_configurado():
        dicas.append(
            "Brave Search autenticou mas retornou 0 resultados — verifique cota/plano da "
            "`BRAVE_SEARCH_API_KEY`"
        )
    else:
        dicas.append("Configure `BRAVE_SEARCH_API_KEY` (busca web e fallbacks nos marketplaces)")

    if ml_configurado():
        dicas.append(
            "API do Mercado Livre (`/sites/search`) costuma retornar 403 — a busca depende de Brave/DDG"
        )

    ddg_msg = mensagem_circuit_breaker("esmaltes_tendencias") or mensagem_circuit_breaker("ml_busca_termo")
    if ddg_msg:
        dicas.append(ddg_msg)
    else:
        dicas.append("DDG sem resultados (comum em IP de datacenter/CI do GitHub Actions)")

    return {
        "coleta_vazia": True,
        "segmentos": len(ok),
        "dicas": dicas,
    }


def _formatar_aviso_coleta_vazia(diag: dict[str, Any]) -> str:
    linhas = [
        "⚠️ *Fontes sem dados* — esta varredura *não* indica ausência de tendências.",
        f"Foram varridos *{diag.get('segmentos', 0)}* segmento(s), mas web e marketplaces retornaram 0.",
        "",
        "*O que verificar:*",
    ]
    for dica in diag.get("dicas") or []:
        linhas.append(f"• {dica}")
    return "\n".join(linhas)


def _carregar_segmentos() -> list[dict[str, Any]]:
    caminho = ROOT / ESMALTES_TENDENCIAS_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        ativos = [s for s in data if isinstance(s, dict) and s.get("ativo")]
        return sorted(ativos, key=lambda x: int(x.get("prioridade") or 99))
    except Exception as exc:
        logger.error("Erro ao carregar catálogo tendências esmaltes: %s", exc)
        return []


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def montar_mensagem_telegram(
    consolidado: dict[str, Any],
    resultados: list[dict[str, Any]],
    *,
    serie: list[dict[str, Any]] | None = None,
    diag_coleta: dict[str, Any] | None = None,
) -> str:
    linhas = [
        "🌐 *Tendências esmaltes — web × marketplaces*",
        "",
        f"Segmentos: *{consolidado.get('segmentos_varridos', 0)}* | "
        f"Hits web: *{consolidado.get('total_web_hits', 0)}* | "
        f"Anúncios MP: *{consolidado.get('total_anuncios_mp', 0)}*",
        "",
    ]

    if diag_coleta and diag_coleta.get("coleta_vazia"):
        linhas.extend([_formatar_aviso_coleta_vazia(diag_coleta), ""])

    if serie:
        comp = formatar_comparativo(serie, _SERIES_CAMPOS)
        if comp:
            linhas.extend([comp, ""])

    oportunidades = consolidado.get("top_oportunidades") or []
    if oportunidades:
        linhas.append("*Oportunidades (tendência web sem oferta forte no MP)*")
        for t in oportunidades[:8]:
            linhas.append(
                f"• *{t.get('cor', '?')}* [{t.get('segmento', '?')}] — "
                f"web {t.get('score_web', 0):.0f}% | MP {t.get('score_mp', 0):.0f}%"
            )
        linhas.append("")

    confirmadas = consolidado.get("top_confirmadas") or []
    if confirmadas:
        linhas.append("*Tendências confirmadas (web + marketplaces)*")
        for t in confirmadas[:6]:
            linhas.append(
                f"• *{t.get('cor', '?')}* [{t.get('segmento', '?')}] — "
                f"web {t.get('mencoes_web', 0)} menções | "
                f"{t.get('peso_vendas_mp', 0)} vendas (proxy MP)"
            )
        linhas.append("")

    termos = consolidado.get("top_termos_web") or []
    if termos:
        linhas.append("*Termos em alta na web*")
        linhas.append(
            ", ".join(
                f"{t.get('termo') or '?'} ({t.get('mencoes') or t.get('mencoes_web') or 0})"
                for t in termos[:8]
                if isinstance(t, dict)
            )
        )
        linhas.append("")

    linhas.append("*Varredura por segmento*")
    for r in resultados:
        if not r.get("ok"):
            continue
        tops = r.get("top_oportunidades") or r.get("top_confirmadas") or []
        destaque = tops[0]["cor"] if tops else "—"
        linhas.append(
            f"• {r.get('nome', '?')}: web {r.get('total_web_hits', 0)} hits | "
            f"MP {r.get('total_anuncios_mp', 0)} anúncios | destaque: {destaque}"
        )

    saturadas = consolidado.get("saturadas_mp") or []
    if saturadas:
        linhas.extend(["", "*Já saturadas nos marketplaces*"])
        for t in saturadas[:4]:
            linhas.append(f"• {t.get('cor', '?')} — {t.get('peso_vendas_mp', 0)} vendas (proxy)")

    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        pode_alertar, motivo_alerta = (True, "ok")
        if enviar_alerta:
            pode_alertar, motivo_alerta = pode_alertar_esmaltes()
            if not pode_alertar:
                logger.warning("Agente não configurado (%s) — Telegram não será enviado", motivo_alerta)

        segmentos = _carregar_segmentos()
        if not segmentos:
            return {"ok": True, "total_segmentos": 0, "consolidado": {}}

        agora = datetime.now(timezone.utc).isoformat()
        buscar_fn = resolver_fn_busca_esmaltes()
        resultados: list[dict[str, Any]] = []

        for i, segmento in enumerate(segmentos):
            logger.info("Tendências esmaltes: %s", segmento.get("nome"))
            resultado = processar_segmento(segmento, buscar_fn)
            resultados.append(resultado)

            gauge(
                "esmaltes.tendencias.web_hits",
                float(resultado.get("total_web_hits") or 0),
                tags=[f"segmento:{segmento.get('id', '?')}"],
            )
            gauge(
                "esmaltes.tendencias.anuncios_mp",
                float(resultado.get("total_anuncios_mp") or 0),
                tags=[f"segmento:{segmento.get('id', '?')}"],
            )
            incrementar(
                "esmaltes.tendencias.varreduras",
                tags=[f"segmento:{segmento.get('id', '?')}"],
            )

            if i < len(segmentos) - 1 and ESMALTES_TENDENCIAS_PAUSA_SEG > 0:
                time.sleep(ESMALTES_TENDENCIAS_PAUSA_SEG)

        consolidado = consolidar_varredura(resultados)
        diag_coleta = diagnosticar_fontes_vazias(resultados)
        if diag_coleta:
            logger.warning(
                "Tendências esmaltes: coleta vazia em %s segmento(s) — fontes sem dados",
                diag_coleta.get("segmentos"),
            )
            consolidado["coleta_vazia"] = True
            consolidado["diag_coleta"] = diag_coleta

        escrever_json_atomico(
            SNAPSHOT_PATH,
            {"timestamp": agora, "consolidado": consolidado, "resultados": resultados},
        )

        serie = registrar_ponto(
            SERIES_PATH,
            {
                "ts": agora,
                "total_web_hits": consolidado.get("total_web_hits") or 0,
                "total_anuncios_mp": consolidado.get("total_anuncios_mp") or 0,
                "oportunidades": len(consolidado.get("top_oportunidades") or []),
                "confirmadas": len(consolidado.get("top_confirmadas") or []),
            },
        )

        historico = ler_json(HISTORY_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}
        historico["ultima_varredura"] = agora
        historico["segmentos"] = consolidado.get("segmentos_varridos")
        historico["top_oportunidade"] = (consolidado.get("top_oportunidades") or [{}])[0].get("cor")
        historico["top_confirmada"] = (consolidado.get("top_confirmadas") or [{}])[0].get("cor")
        escrever_json_atomico(HISTORY_PATH, historico)

        alerta_enviado = False
        if enviar_alerta and ESMALTES_TENDENCIAS_ALERTA_RESUMO and pode_alertar:
            msg = montar_mensagem_telegram(
                consolidado, resultados, serie=serie, diag_coleta=diag_coleta
            )
            chave = chave_resumo_periodo("esmaltes:tendencias", horas_por_bucket=12)
            alerta_enviado = bool(
                alertar_gestor(msg, chave=chave, cooldown_segundos=ESMALTES_TENDENCIAS_ALERTA_COOLDOWN_SEG)
            )
            grafico = grafico_evolucao(
                serie, _SERIES_CAMPOS, GRAFICO_PATH, titulo="Tendências esmaltes — evolução"
            )
            if grafico:
                enviar_foto_gestor(
                    str(grafico),
                    "📊 Tendências esmaltes — web × MP ao longo do tempo",
                    chave=f"{chave}:grafico",
                    cooldown_segundos=ESMALTES_TENDENCIAS_ALERTA_COOLDOWN_SEG,
                )

        gauge("esmaltes.tendencias.oportunidades", float(len(consolidado.get("top_oportunidades") or [])))
        gauge("esmaltes.tendencias.confirmadas", float(len(consolidado.get("top_confirmadas") or [])))
        incrementar("esmaltes.tendencias.rodadas")

        return {
            "ok": True,
            "total_segmentos": len(resultados),
            "consolidado": consolidado,
            "coleta_vazia": bool(diag_coleta),
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente tendências esmaltes erro: %s", exc)
        incrementar("esmaltes.tendencias.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor tendências esmaltes — web × marketplaces")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Monitor tendências esmaltes (web × MP) ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    c = out.get("consolidado") or {}
    logger.info(
        "Concluído: %s segmento(s), %s oportunidade(s), %s confirmada(s), alerta=%s",
        out.get("total_segmentos"),
        len(c.get("top_oportunidades") or []),
        len(c.get("top_confirmadas") or []),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
