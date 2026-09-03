"""
agentes/ml/agente_relatorio_manha_ml.py
Relatório matinal ML: visão dos seus anúncios vs mercado + propostas com lucro viável.

Consolida monitor ML, inteligência de preços, concorrentes e Anita em um único alerta.

Uso:
  python -m agentes.ml.agente_relatorio_manha_ml
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import ML_RELATORIO_MANHA_COOLDOWN_SEG, ROOT
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado

logger = logging.getLogger("agente_relatorio_manha_ml")

SNAPSHOT_PATH = ROOT / "logs" / "relatorio_manha_ml_ultima.json"


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _montar_secao_conta(ml: dict[str, Any]) -> list[str]:
    conta = ml.get("conta") or {}
    ads = ml.get("ads") or {}
    linhas = ["📊 *Sua conta ML*", ""]
    linhas.append(f"• Perguntas pendentes: {conta.get('perguntas_pendentes', 0)}")
    saude = conta.get("saude") or {}
    if saude:
        linhas.append(
            f"• Claims: {float(saude.get('claims_rate', 0)) * 100:.1f}% | "
            f"Dias sem acesso: {saude.get('dias_sem_acesso', '?')}"
        )
    if ads.get("configurado"):
        linhas.append(
            f"• Ads: {ads.get('campanhas_ativas', 0)}/{ads.get('total_campanhas', 0)} ativas | "
            f"Gasto R$ {float(ads.get('gasto_total', 0)):.2f}"
        )
    else:
        linhas.append(f"• Ads: {ads.get('pendencia', 'não consultado')}")
    return linhas


def _montar_secao_anuncios(ml: dict[str, Any]) -> list[str]:
    itens = ml.get("concorrencia") or []
    linhas = ["", "🔎 *Seus anúncios vs mercado*", ""]
    if not itens:
        linhas.append("_Nenhum anúncio analisado (verifique token ML)._")
        return linhas
    for item in itens[:8]:
        titulo = str(item.get("titulo") or item.get("item_id") or "?")[:42]
        meu = float(item.get("meu_preco") or 0)
        conc = float(item.get("menor_concorrente") or 0)
        visitas = item.get("visitas_7d")
        diff = item.get("diff_preco_pct")
        status = "✅ competitivo"
        if conc > 0 and meu > conc * 1.05:
            status = f"⚠️ +{diff or 0:.0f}% acima do menor"
        elif conc > 0 and meu <= conc:
            status = "🏆 menor ou igual ao concorrente"
        linhas.append(
            f"• {titulo}\n"
            f"  Seu {_fmt_brl(meu)} vs conc. {_fmt_brl(conc) if conc else 'n/d'} | "
            f"👁 {visitas or 0}/7d | {status}"
        )
    if len(itens) > 8:
        linhas.append(f"  … +{len(itens) - 8} anúncio(s)")
    return linhas


def _montar_secao_propostas(analises_ml: list[dict[str, Any]]) -> list[str]:
    linhas = ["", "💰 *Propostas de preço (lucro viável)*", ""]
    candidatas = [
        a
        for a in analises_ml
        if abs(float(a.get("delta") or 0)) >= 0.5
        and (a.get("lucro_operacao") or {}).get("lucro_ok", True)
    ]
    candidatas.sort(
        key=lambda x: (
            0 if x.get("prioridade") == "alta" else 1 if x.get("prioridade") == "media" else 2,
            -abs(float(x.get("delta") or 0)),
        )
    )
    if not candidatas:
        linhas.append("_Preços atuais dentro da margem — sem alteração sugerida hoje._")
        return linhas

    for item in candidatas[:10]:
        lucro = item.get("lucro_operacao") or {}
        delta = float(item.get("delta") or 0)
        linhas.append(
            f"• *{item.get('sku', '?')}*: {_fmt_brl(item.get('preco_atual'))} → "
            f"{_fmt_brl(item.get('preco_sugerido'))} ({delta:+.2f})\n"
            f"  {item.get('acao', '')} | margem {lucro.get('margem_sugerida_pct', '?')}% "
            f"(mín {item.get('margem_minima_pct', '?')}%) | lucro {_fmt_brl(lucro.get('sugerido_reais'))}"
        )
        if item.get("preco_concorrente"):
            linhas.append(f"  Concorrência: {_fmt_brl(item['preco_concorrente'])}")
    if len(candidatas) > 10:
        linhas.append(f"  … +{len(candidatas) - 10} proposta(s) no snapshot JSON")
    return linhas


def _montar_secao_concorrentes_termo(conc: dict[str, Any]) -> list[str]:
    resultados = conc.get("resultados") or []
    alertas = conc.get("alertas") or []
    if not resultados and not alertas:
        return []
    linhas = ["", "📋 *Concorrentes por termo (catálogo)*", ""]
    for alerta in alertas[:5]:
        linhas.append(f"• {alerta}")
    if not alertas:
        for r in resultados[:4]:
            tend = ""
            td = r.get("tendencia_demanda") if isinstance(r.get("tendencia_demanda"), dict) else {}
            if td.get("tendencia") in {"alta", "queda", "estavel"}:
                tend = f" | demanda {td.get('tendencia')}"
            linhas.append(
                f"• {r.get('nome', '?')}: menor {_fmt_brl(r.get('menor_preco'))} "
                f"(seu {_fmt_brl(r.get('meu_preco'))}){tend}"
            )
            padroes = r.get("padroes_reclamacao") or []
            if padroes:
                top = ", ".join(
                    f"{p.get('padrao')}×{p.get('frequencia')}"
                    for p in padroes[:2]
                    if isinstance(p, dict)
                )
                if top:
                    linhas.append(f"  reclamações: {top}")
    return linhas


def _montar_secao_anita(anita: dict[str, Any]) -> list[str]:
    resultados = anita.get("resultados") or []
    if not resultados:
        return []
    linhas = ["", "💅 *Anita — cores e kits*", ""]
    ranking: dict[str, int] = {}
    for r in resultados:
        for item in r.get("ranking_marcas") or []:
            marca = str(item.get("marca") or "?")
            ranking[marca] = ranking.get(marca, 0) + int(item.get("vendidos") or 0)
    if ranking:
        top = sorted(ranking.items(), key=lambda x: x[1], reverse=True)[:3]
        linhas.append("Marca mais vendida: " + ", ".join(f"{m} ({v})" for m, v in top))
    for r in resultados[:3]:
        margem = (r.get("margem_minha") or {}).get("margem_operacional_pct")
        linhas.append(
            f"• {r.get('nome', '?')}: líder {r.get('marca_mais_vendida', '?')} | "
            f"margem {margem or 'n/d'}%"
        )
    return linhas


def _montar_secao_mercado_esmaltes(mercado: dict[str, Any]) -> list[str]:
    consolidado = mercado.get("consolidado") or {}
    propostas = consolidado.get("propostas") or []
    if not propostas and not consolidado.get("total_anuncios_unicos"):
        return []

    linhas = [
        "",
        "💄 *Mercado esmaltes — competir com margem*",
        "",
        f"_{consolidado.get('total_anuncios_unicos', 0)} anúncios | "
        f"{consolidado.get('total_oportunidades_margem', 0)} oportunidade(s) viável(eis)_",
        "",
    ]

    ranking = consolidado.get("ranking_marcas_global") or []
    if ranking:
        top = ", ".join(f"{x['marca']} ({x['vendidos']})" for x in ranking[:3])
        linhas.append(f"Marcas líderes: {top}")
        linhas.append("")

    altas = [p for p in propostas if p.get("prioridade") == "alta"]
    medias = [p for p in propostas if p.get("prioridade") == "media"]

    for p in altas[:4]:
        texto = str(p.get("texto") or "").replace("*", "")
        linhas.append(f"• {texto}")
    for p in medias[:3]:
        texto = str(p.get("texto") or "").replace("*", "")
        linhas.append(f"• {texto}")

    top_anuncios = consolidado.get("top_anuncios") or []
    if top_anuncios:
        linhas.append("")
        linhas.append("_Top anúncios (cores e kits):_")
        for an in top_anuncios[:3]:
            titulo = str(an.get("titulo") or "")[:45]
            linhas.append(
                f"  {titulo} — {_fmt_brl(an.get('preco'))} | "
                f"{an.get('descricao_kit', '')}"
            )
    return linhas


def _montar_secao_acoes(
    ml: dict[str, Any],
    propostas: list[dict[str, Any]],
    mercado: dict[str, Any] | None = None,
) -> list[str]:
    recs = list(ml.get("recomendacoes") or [])[:5]
    linhas = ["", "✅ *Prioridades do dia*", ""]
    n = 1
    for p in propostas:
        if p.get("prioridade") != "alta":
            continue
        linhas.append(f"{n}. Ajustar *{p.get('sku')}* → {_fmt_brl(p.get('preco_sugerido'))}")
        n += 1
    if mercado:
        for p in (mercado.get("consolidado") or {}).get("propostas") or []:
            if p.get("prioridade") != "alta" or n > 8:
                continue
            sku = p.get("sku") or "esmalte"
            preco = p.get("preco_sugerido")
            if preco:
                linhas.append(f"{n}. Mercado *{sku}* → {_fmt_brl(preco)}")
                n += 1
    for rec in recs:
        if n > 8:
            break
        linhas.append(f"{n}. {rec}")
        n += 1
    if n == 1:
        linhas.append("1. Manter estratégia atual — margens dentro do esperado.")
    return linhas


def _montar_relatorio(
    ml: dict[str, Any],
    precos: dict[str, Any],
    conc: dict[str, Any],
    anita: dict[str, Any],
    mercado: dict[str, Any] | None = None,
) -> str:
    analises = precos.get("analises") or []
    analises_ml = [a for a in analises if str(a.get("canal", "")).lower() == "mercadolivre"]
    propostas = [
        a
        for a in analises_ml
        if abs(float(a.get("delta") or 0)) >= 0.5
        and (a.get("lucro_operacao") or {}).get("lucro_ok", True)
    ]

    agora = datetime.now(timezone(timedelta(hours=-3)))
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente("relatorio_manha_ml", "☀️ *Relatório manhã — Mercado Livre*"),
        f"_{agora.strftime('%d/%m/%Y %H:%M')}_",
        "",
        "_Lucro = preço − taxa ML − custo | respeita margem mínima por fase_",
    ]
    linhas.extend(_montar_secao_conta(ml))
    linhas.extend(_montar_secao_anuncios(ml))
    linhas.extend(_montar_secao_propostas(analises_ml))
    linhas.extend(_montar_secao_concorrentes_termo(conc))
    linhas.extend(_montar_secao_anita(anita))
    if mercado:
        linhas.extend(_montar_secao_mercado_esmaltes(mercado))
    linhas.extend(_montar_secao_acoes(ml, propostas, mercado))
    return "\n".join(linhas).strip()


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — relatório manhã não será enviado")

        from agentes.esmaltes.agente_monitor_anita import executar as executar_anita
        from agentes.esmaltes.agente_monitor_mercado_esmaltes import executar as executar_mercado_esmaltes
        from agentes.ml.agente_monitor_concorrentes import executar as executar_concorrentes
        from agentes.ml.agente_monitor_ml import analisar as analisar_ml
        from agentes.precificacao.agente_inteligencia_precos import executar as executar_precos

        logger.info("Relatório manhã ML: coletando dados...")
        ml = analisar_ml(enviar_alerta=False)
        precos = executar_precos(enviar_alerta=False)
        conc = executar_concorrentes(enviar_alerta=False)
        anita = executar_anita(enviar_alerta=False)
        mercado = executar_mercado_esmaltes(enviar_alerta=False)

        relatorio = _montar_relatorio(ml, precos, conc, anita, mercado)
        agora = datetime.now(timezone.utc).isoformat()

        snapshot = {
            "timestamp": agora,
            "ml_ok": ml.get("ok"),
            "total_propostas": len(
                [
                    a
                    for a in (precos.get("analises") or [])
                    if str(a.get("canal", "")).lower() == "mercadolivre"
                    and abs(float(a.get("delta") or 0)) >= 0.5
                ]
            ),
            "relatorio": relatorio,
        }
        escrever_json_atomico(SNAPSHOT_PATH, snapshot)

        alerta_enviado = False
        if enviar_alerta and relatorio:
            alerta_enviado = bool(
                alertar_gestor(
                    relatorio,
                    chave=chave_resumo_periodo("ml:relatorio:manha", horas_por_bucket=12),
                    cooldown_segundos=ML_RELATORIO_MANHA_COOLDOWN_SEG,
                    agente_id="relatorio_manha_ml",
                )
            )

        incrementar("ml.relatorio_manha.rodadas", tags=[f"ok:{ml.get('ok', False)}"])
        return {
            "ok": True,
            "ml": ml,
            "precos": precos,
            "concorrentes": conc,
            "anita": anita,
            "mercado_esmaltes": mercado,
            "alerta_enviado": alerta_enviado,
            "relatorio": relatorio,
            "snapshot": str(SNAPSHOT_PATH),
        }
    except Exception as exc:
        logger.error("Relatório manhã ML erro: %s", exc)
        return {"ok": False, "erro": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Relatório matinal ML consolidado")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Relatório manhã Mercado Livre ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    logger.info("Relatório manhã enviado=%s", out.get("alerta_enviado"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
