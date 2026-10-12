"""
agentes/precificacao/agente_inteligencia_precos.py
Monitora comportamento de compra em todos os marketplaces do catálogo
e sugere preços que atraem vendas respeitando margem mínima.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.catalogo_produtos import carregar_produtos_para_operacao
from core.config import (
    LUCRO_MINIMO_REPRICING_PCT,
    MARGEM_FASE_1_PCT,
    MARGEM_FASE_2_PCT,
    MARGEM_FASE_3_PCT,
    MONITOR_CONCORRENTES_ARQUIVO,
    PRECIFICACAO_ALERTA_PAINEL_COOLDOWN_SEG,
    PRECIFICACAO_MIN_VISITAS_7D_ALERTA,
    REPRICING_ABAIXO_CONCORRENTE_PCT,
    ROOT,
    TAXA_CANAL_PADRAO_PCT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from core.precificacao_comportamento import calcular_preco_ideal
from integracoes.marketplaces.sinais_comprador import coletar_sinais

logger = logging.getLogger("agente_inteligencia_precos")

SNAPSHOT_PATH = ROOT / "logs" / "precificacao_inteligencia_ultima_rodada.json"
HISTORY_PATH = ROOT / "logs" / "precificacao_inteligencia_history.json"


def _margem_minima_por_fase(fase_atual: int | str | None) -> float:
    fase = str(fase_atual or "1").strip()
    if fase == "2":
        return MARGEM_FASE_2_PCT
    if fase == "3":
        return MARGEM_FASE_3_PCT
    return MARGEM_FASE_1_PCT


def _preco_fase(produto: dict[str, Any]) -> float | None:
    fase = str(produto.get("fase_atual") or "1").strip()
    chave = f"fase{fase}"
    por_fase = produto.get("precos_por_fase") or {}
    try:
        v = float(por_fase.get(chave) or 0)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _carregar_monitor_por_sku() -> dict[str, dict[str, Any]]:
    caminho = ROOT / MONITOR_CONCORRENTES_ARQUIVO
    try:
        if not caminho.is_file():
            return {}
        data = json.loads(caminho.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return {}
        return {
            str(ent["sku"]).strip(): ent
            for ent in data
            if isinstance(ent, dict) and ent.get("ativo") and ent.get("sku")
        }
    except Exception as exc:
        logger.warning("inteligencia_precos monitor: %s", exc)
        return {}


def _analisar_canal(
    produto: dict[str, Any],
    canal: str,
    dados: dict[str, Any],
    *,
    monitor_por_sku: dict[str, dict[str, Any]],
    lucro_minimo_pct: float,
) -> dict[str, Any] | None:
    sku = str(produto.get("sku") or "").strip()
    custo = float(produto.get("custo") or 0)
    if custo <= 0:
        return None

    preco_atual = float(dados.get("preco") or produto.get("preco") or 0)
    fase_atual = produto.get("fase_atual", 1)
    margem_minima = max(lucro_minimo_pct, _margem_minima_por_fase(fase_atual))
    taxa_canal = float(dados.get("taxa_canal_pct") or TAXA_CANAL_PADRAO_PCT)

    termo = str(dados.get("termo_busca") or "").strip()
    if not termo and sku in monitor_por_sku:
        termo = str(monitor_por_sku[sku].get("termo_busca") or "").strip()

    sinais_raw = coletar_sinais(canal, dados, sku=sku, termo_busca=termo)
    preco_concorrente = float(dados.get("preco_concorrente") or 0)
    if preco_concorrente <= 0:
        preco_concorrente = float(sinais_raw.get("preco_concorrente_vivo") or sinais_raw.get("menor_preco") or 0)

    sinais = {
        "visitas_7d": sinais_raw.get("visitas_7d"),
        "visitas_30d": sinais_raw.get("visitas_30d"),
        "unidades_vendidas_7d": sinais_raw.get("unidades_vendidas_7d"),
        "vendas_por_dia": sinais_raw.get("vendas_por_dia"),
        "preco_sugerido_ml": sinais_raw.get("preco_sugerido_ml"),
        "quantidade_vendida_lider": sinais_raw.get("quantidade_vendida_lider"),
    }

    ideal = calcular_preco_ideal(
        preco_atual=preco_atual,
        custo=custo,
        preco_concorrente=preco_concorrente or None,
        margem_minima_pct=margem_minima,
        taxa_canal_pct=taxa_canal,
        abaixo_concorrente_pct=REPRICING_ABAIXO_CONCORRENTE_PCT,
        sinais=sinais,
        preco_fase=_preco_fase(produto),
    )

    delta = round(ideal["preco_sugerido"] - preco_atual, 2)
    prioridade = "baixa"
    if ideal["acao"] == "reduzir para atrair vendas":
        prioridade = "alta"
    elif ideal["acao"] == "monitorar — tráfego sem conversão":
        prioridade = "media"
    elif ideal["acao"] == "subir — demanda suporta":
        prioridade = "media"

    return {
        "sku": sku,
        "nome": produto.get("nome") or sku,
        "canal": canal,
        "custo": ideal.get("custo", custo),
        "taxa_canal_pct": ideal.get("taxa_canal_pct", taxa_canal),
        "preco_atual": preco_atual,
        "preco_sugerido": ideal["preco_sugerido"],
        "preco_piso": ideal.get("preco_piso"),
        "delta": delta,
        "acao": ideal["acao"],
        "comportamento": ideal["comportamento"],
        "motivos": ideal["motivos"],
        "margem_pct": ideal["margem_pct"],
        "margem_minima_pct": ideal.get("margem_minima_pct", margem_minima),
        "lucro_operacao": ideal.get("lucro_operacao", {}),
        "preco_concorrente": ideal.get("preco_concorrente"),
        "prioridade": prioridade,
        "sinais": {**ideal.get("sinais", {}), "termo_busca": termo or None},
        "sinais_brutos": sinais_raw,
    }


def _formatar_lucro_operacao(item: dict[str, Any]) -> str:
    lucro = item.get("lucro_operacao") or {}
    atual = lucro.get("atual_reais")
    sugerido = lucro.get("sugerido_reais")
    margem_sug = lucro.get("margem_sugerida_pct")
    margem_min = item.get("margem_minima_pct")
    if atual is None or sugerido is None:
        return ""
    delta_lucro = lucro.get("delta_lucro_reais", round(sugerido - atual, 2))
    sinal = f"{delta_lucro:+.2f}"
    status = "✓" if lucro.get("lucro_ok", True) else "⚠ piso"
    return (
        f"\n  💵 Lucro operação: R$ {atual:.2f} → R$ {sugerido:.2f} ({sinal}) | "
        f"margem {margem_sug:.1f}% (mín {margem_min:.0f}%) {status}"
    )


def _formatar_linha(item: dict[str, Any]) -> str:
    delta = item.get("delta") or 0
    sinal_delta = f"{delta:+.2f}" if delta else "="
    visitas = item.get("sinais", {}).get("visitas_7d")
    vendas = item.get("sinais", {}).get("unidades_vendidas_7d")
    visitas_txt = f" | 👁 {visitas}v/7d" if visitas is not None else ""
    vendas_txt = f" | 🛒 {vendas}u/7d" if vendas is not None else ""
    lucro_txt = _formatar_lucro_operacao(item)
    return (
        f"• {item['sku']} ({item['canal']}): R$ {item['preco_atual']:.2f} → "
        f"R$ {item['preco_sugerido']:.2f} ({sinal_delta}) — {item['acao']}"
        f"{visitas_txt}{vendas_txt}{lucro_txt}"
    )


def _montar_painel_telegram(analises: list[dict[str, Any]], *, total_skus: int) -> str:
    from core.telegram_explicacao import inserir_explicacao

    alta = [a for a in analises if a.get("prioridade") == "alta"]
    media = [a for a in analises if a.get("prioridade") == "media"]
    ordenados = alta + media + [a for a in analises if a.get("prioridade") == "baixa"]
    linhas = [_formatar_linha(a) for a in ordenados[:12]]
    if len(ordenados) > 12:
        linhas.append(f"… +{len(ordenados) - 12} itens no snapshot JSON")

    reduzir = sum(1 for a in analises if "reduzir" in str(a.get("acao", "")))
    monitorar = sum(1 for a in analises if "monitorar" in str(a.get("acao", "")))
    subir = sum(1 for a in analises if "subir" in str(a.get("acao", "")))

    return inserir_explicacao(
        "💰 *SUGESTÃO (não aplicada)* — Inteligência de preços\n"
        f"SKUs no catálogo: {total_skus} | canais analisados: {len(analises)}\n"
        f"Lucro = preço − taxa marketplace − custo | mínimo por fase em spec\n"
        f"Sugestões: ↓{reduzir} reduzir | 👀{monitorar} monitorar | ↑{subir} subir\n"
        "_Preço só muda no job de repricing (operação 24h / 2h), não neste ciclo._\n\n"
        + ("\n".join(linhas) if linhas else "Nenhum canal ativo no catálogo."),
        "inteligencia_precos",
    )


def executar(*, enviar_alerta: bool = True, lucro_minimo_pct: float | None = None) -> dict[str, Any]:
    lucro_minimo = float(lucro_minimo_pct if lucro_minimo_pct is not None else LUCRO_MINIMO_REPRICING_PCT)
    produtos = carregar_produtos_para_operacao()
    monitor_por_sku = _carregar_monitor_por_sku()
    analises: list[dict[str, Any]] = []

    for produto in produtos:
        canais = produto.get("canais") or {}
        if not isinstance(canais, dict):
            continue
        for canal, dados in canais.items():
            if not isinstance(dados, dict) or not dados.get("ativo"):
                continue
            item = _analisar_canal(
                produto,
                str(canal),
                dados,
                monitor_por_sku=monitor_por_sku,
                lucro_minimo_pct=lucro_minimo,
            )
            if item:
                analises.append(item)
                logger.debug(
                    "Precificação %s/%s: atual=%.2f sugerido=%.2f lucro=%.2f→%.2f acao=%s",
                    item["sku"],
                    item["canal"],
                    item["preco_atual"],
                    item["preco_sugerido"],
                    (item.get("lucro_operacao") or {}).get("atual_reais", 0),
                    (item.get("lucro_operacao") or {}).get("sugerido_reais", 0),
                    item["acao"],
                )

    agora = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "timestamp": agora,
        "total_produtos_catalogo": len(produtos),
        "total_analises": len(analises),
        "analises": analises,
    }
    escrever_json_atomico(SNAPSHOT_PATH, snapshot)

    historico = ler_json(HISTORY_PATH, default=[])
    if not isinstance(historico, list):
        historico = []
    historico.append(
        {
            "timestamp": agora,
            "total_analises": len(analises),
            "reduzir": sum(1 for a in analises if "reduzir" in str(a.get("acao", ""))),
            "monitorar": sum(1 for a in analises if "monitorar" in str(a.get("acao", ""))),
        }
    )
    escrever_json_atomico(HISTORY_PATH, historico[-90:])

    incrementar("precificacao.inteligencia.rodadas")
    gauge("precificacao.inteligencia.analises", len(analises))

    alerta_enviado = False
    if enviar_alerta and analises and gestor_telegram_configurado():
        texto = _montar_painel_telegram(analises, total_skus=len(produtos))
        alerta_enviado = bool(
            alertar_gestor(
                texto,
                chave=chave_resumo_periodo("precificacao:painel", horas_por_bucket=24),
                cooldown_segundos=PRECIFICACAO_ALERTA_PAINEL_COOLDOWN_SEG,
                agente_id="inteligencia_precos",
            )
        )
        if not alerta_enviado:
            logger.info("Painel precificação não enviado (cooldown ou Telegram indisponível)")

        urgentes = [
            a
            for a in analises
            if a.get("prioridade") == "alta"
            or (
                int(a.get("sinais", {}).get("visitas_7d") or 0) >= PRECIFICACAO_MIN_VISITAS_7D_ALERTA
                and int(a.get("sinais", {}).get("unidades_vendidas_7d") or 0) == 0
            )
        ]
        if urgentes:
            from core.telegram_explicacao import inserir_explicacao

            linhas_urg = [_formatar_linha(u) for u in urgentes[:5]]
            alertar_gestor(
                inserir_explicacao(
                    "⚡ Preço para atrair vendas (com lucro operacional):\n"
                    + "\n".join(linhas_urg),
                    "inteligencia_precos",
                ),
                agente_id="inteligencia_precos",
            )

    resultado = {
        "ok": True,
        "total_produtos": len(produtos),
        "total_analises": len(analises),
        "alerta_enviado": alerta_enviado,
        "snapshot": str(SNAPSHOT_PATH),
        "analises": analises,
    }
    logger.info("Inteligência preços: %d análises", len(analises))
    return resultado


if __name__ == "__main__":
    executar(enviar_alerta=True)
