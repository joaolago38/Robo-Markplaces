"""
agentes/esmaltes/agente_monitor_kits_esmaltes.py
Monitora anúncios de kits de esmaltes no ML (radar de mercado): preços, marcas e proxy de vendas.

Catálogo: catalogo/esmaltes_kits_monitor.json

Uso:
  python -m agentes.esmaltes.agente_monitor_kits_esmaltes
  python -m agentes.esmaltes.agente_monitor_kits_esmaltes --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    ESMALTES_KITS_MONITOR_ALERTA_COOLDOWN_SEG,
    ESMALTES_KITS_MONITOR_ALERTA_RESUMO,
    ESMALTES_KITS_MONITOR_CATALOGO,
    ESMALTES_KITS_MONITOR_PAUSA_SEG,
    MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.graficos import grafico_evolucao
from core.notificador import alertar_gestor, chave_resumo_periodo, enviar_foto_gestor
from core.prontidao import pode_alertar_esmaltes
from core.series_historica import formatar_comparativo, registrar_ponto
from integracoes.esmaltes.analise_kits_esmaltes import (
    consolidar_varredura,
    deltas_preco_itens,
    enriquecer_top_kits,
    fmt_vendas_proxy,
    processar_termo,
    snapshot_itens_preco,
    vendas_tem_dado,
)
from integracoes.marketplaces.busca_multi_marketplace import (
    formatar_secao_por_marketplace,
    resolver_fn_busca_esmaltes,
)

logger = logging.getLogger("agente_monitor_kits_esmaltes")

SNAPSHOT_PATH = ROOT / "logs" / "esmaltes_kits_monitor_ultima.json"
HISTORY_PATH = ROOT / "logs" / "esmaltes_kits_monitor_history.json"
SERIES_PATH = ROOT / "logs" / "esmaltes_kits_monitor_series.json"
GRAFICO_PATH = ROOT / "logs" / "esmaltes_kits_monitor_grafico.png"

_SERIES_CAMPOS = [
    ("total_kits", "Kits únicos"),
    ("total_vendas", "Vendas (proxy)"),
    ("preco_medio", "Preço médio"),
]


def _carregar_termos() -> list[dict[str, Any]]:
    caminho = ROOT / ESMALTES_KITS_MONITOR_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        ativos = [t for t in data if isinstance(t, dict) and t.get("ativo")]
        return sorted(ativos, key=lambda x: int(x.get("prioridade") or 99))
    except Exception as exc:
        logger.error("Erro ao carregar catálogo kits esmaltes: %s", exc)
        return []


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _fmt_vendas_marca(item: dict[str, Any]) -> str:
    return fmt_vendas_proxy(item.get("vendidos"))


def _linha_top_anuncio(an: dict[str, Any], idx: int) -> str:
    titulo = str(an.get("titulo") or "?")[:55]
    vendas = fmt_vendas_proxy(an.get("quantidade_vendida"))
    pedacos = [
        f"{idx}. {titulo} — {_fmt_brl(an.get('preco'))}",
        vendas if vendas != "n/d" else "vendas n/d",
        str(an.get("marca") or "?"),
    ]
    if not vendas_tem_dado(an):
        aval = an.get("avaliacoes")
        nota = an.get("nota")
        if aval:
            if nota is not None:
                pedacos.append(f"★{nota} ({aval} aval.)")
            else:
                pedacos.append(f"{aval} aval.")
    return " | ".join(pedacos)


def montar_mensagem_telegram(
    consolidado: dict[str, Any],
    resultados: list[dict[str, Any]],
    *,
    serie: list[dict[str, Any]] | None = None,
    deltas: list[str] | None = None,
    agir: dict[str, Any] | None = None,
) -> str:
    from core.telegram_explicacao import cabecalho_agente

    total_vendas = int(consolidado.get("total_vendas") or 0)
    com_dado = int(consolidado.get("kits_com_vendas_api") or 0)
    if consolidado.get("vendas_proxy_confiavel") and total_vendas > 0:
        linha_vendas = (
            f"Vendas (proxy, {com_dado} anúncio(s) com dado API): "
            f"*{total_vendas:,}*".replace(",", ".")
        )
    else:
        linha_vendas = "Vendas (proxy): *n/d* — API sem `sold_quantity` nesta amostra"

    linhas = [
        cabecalho_agente(
            "monitor_kits_esmaltes",
            "🎨 *Kits esmaltes — radar de mercado (amostra)*",
        ),
        "_Busca por termo · não é painel da sua conta nem vendas reais do rival._",
        "",
        f"Kits únicos: *{consolidado.get('total_kits_unicos', 0)}* | {linha_vendas}",
        f"Preços: {_fmt_brl(consolidado.get('preco_min'))} – "
        f"{_fmt_brl(consolidado.get('preco_max'))} | média {_fmt_brl(consolidado.get('preco_medio'))}",
        f"Termos varridos: {consolidado.get('termos_varridos', 0)}"
        + (
            f" | enriquecidos: {consolidado.get('enriquecidos', 0)}"
            if consolidado.get("enriquecidos")
            else ""
        ),
    ]
    if serie:
        comp = formatar_comparativo(
            serie, [("total_kits", "Kits"), ("total_vendas", "Vendas"), ("preco_medio", "Preço médio", 2)]
        )
        if comp:
            linhas.extend(["", comp])
    linhas.append(formatar_secao_por_marketplace(consolidado, fmt_brl=_fmt_brl))

    if deltas:
        linhas.extend(["", "*Mudanças vs rodada anterior (preço/presença)*"])
        for d in deltas:
            linhas.append(f"• {d}")

    linhas.extend(["", "*Marcas (presença na amostra)*"])

    ranking = consolidado.get("ranking_marcas") or []
    if ranking:
        for item in ranking[:8]:
            linhas.append(
                f"• {item.get('marca', '?')}: {_fmt_vendas_marca(item)} | "
                f"{item.get('anuncios', 0)} anúncio(s) | média {_fmt_brl(item.get('preco_medio'))}"
            )
    else:
        linhas.append("_Nenhuma marca nesta rodada._")

    padroes = consolidado.get("padroes_tamanho") or []
    if padroes:
        linhas.extend(["", "*Por tamanho de kit*"])
        for p in padroes[:6]:
            linhas.append(
                f"• Kit {p.get('qtd')}: {p.get('anuncios', 0)} anúncio(s) | "
                f"{fmt_vendas_proxy(p.get('vendidos'))} | média {_fmt_brl(p.get('preco_medio'))}"
            )

    top = consolidado.get("top_vendas") or []
    if top:
        linhas.extend(["", "*Top anúncios (amostra)*"])
        for i, an in enumerate(top[:10], 1):
            linhas.append(_linha_top_anuncio(an, i))

    linhas.extend(["", "*Varredura por termo*"])
    for r in resultados:
        if not r.get("ok"):
            continue
        linhas.append(
            f"• {r.get('nome', '?')}: `{r.get('termo_busca', '')}` → "
            f"{r.get('total_kits', 0)} kit(s) de {r.get('total_bruto', 0)} anúncio(s)"
        )

    try:
        from integracoes.esmaltes.decisao_batalha_agir import formatar_secao_agir

        linhas.extend(formatar_secao_agir(agir))
        if isinstance(agir, dict) and agir.get("resumo_claude"):
            linhas.extend(["", f"_IA:_ {agir.get('resumo_claude')}"])
    except Exception:
        pass

    linhas.extend(
        [
            "",
            "_Legenda: `n/d` = API não informou vendas. Avaliações = proxy fraco. "
            "Para certeza alta de preço/status do rival, use a watchlist MLB "
            "(monitor concorrentes tipo `item`)._",
        ]
    )
    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        pode_alertar, motivo_alerta = (True, "ok")
        if enviar_alerta:
            pode_alertar, motivo_alerta = pode_alertar_esmaltes()
            if not pode_alertar:
                logger.warning("Agente não configurado (%s) — Telegram não será enviado", motivo_alerta)

        termos = _carregar_termos()
        if not termos:
            return {"ok": True, "total_termos": 0, "consolidado": {}}

        agora = datetime.now(timezone.utc).isoformat()
        resultados: list[dict[str, Any]] = []

        for i, segmento in enumerate(termos):
            termo = str(segmento.get("termo_busca") or "").strip()
            limite = int(segmento.get("limite_resultados") or 25)
            if not termo:
                continue
            logger.info("Varredura kits esmaltes: %s", termo)
            buscar_fn = resolver_fn_busca_esmaltes()
            anuncios = buscar_fn(termo, limite=limite)
            resultado = processar_termo(segmento, anuncios)
            resultados.append(resultado)

            gauge(
                "esmaltes.kits.anuncios",
                float(resultado.get("total_kits") or 0),
                tags=[f"termo:{segmento.get('id', '?')}"],
            )
            incrementar("esmaltes.kits.varreduras", tags=[f"termo:{segmento.get('id', '?')}"])

            if i < len(termos) - 1 and ESMALTES_KITS_MONITOR_PAUSA_SEG > 0:
                time.sleep(ESMALTES_KITS_MONITOR_PAUSA_SEG)

        consolidado = consolidar_varredura(resultados)
        try:
            consolidado = enriquecer_top_kits(consolidado)
        except Exception as exc:
            logger.warning("enrich top kits falhou: %s", exc)

        historico = ler_json(HISTORY_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}
        snap_itens = snapshot_itens_preco(
            consolidado.get("kits_unicos") or consolidado.get("top_vendas") or []
        )
        deltas = deltas_preco_itens(
            snap_itens,
            historico.get("itens") if isinstance(historico.get("itens"), dict) else {},
            variacao_alerta_pct=MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT,
        )

        escrever_json_atomico(
            SNAPSHOT_PATH,
            {
                "timestamp": agora,
                "consolidado": consolidado,
                "resultados": resultados,
                "deltas": deltas,
            },
        )

        serie = registrar_ponto(
            SERIES_PATH,
            {
                "ts": agora,
                "total_kits": consolidado.get("total_kits_unicos") or 0,
                "total_vendas": consolidado.get("total_vendas") or 0,
                "preco_medio": consolidado.get("preco_medio") or 0,
            },
        )

        historico["ultima_varredura"] = agora
        historico["total_kits_unicos"] = consolidado.get("total_kits_unicos")
        historico["total_vendas"] = consolidado.get("total_vendas")
        historico["kits_com_vendas_api"] = consolidado.get("kits_com_vendas_api")
        historico["lider_marca"] = (consolidado.get("ranking_marcas") or [{}])[0].get("marca")
        historico["itens"] = snap_itens
        historico["deltas_ultima"] = deltas
        escrever_json_atomico(HISTORY_PATH, historico)

        batalha_out: dict[str, Any] = {}
        try:
            from integracoes.esmaltes.metricas_batalha_impala import processar_e_persistir

            batalha_out = processar_e_persistir(
                list(consolidado.get("kits_unicos") or []),
                origem="kits_monitor",
            )
        except Exception as exc:
            logger.warning("batalha Impala métricas: %s", exc)

        alerta_enviado = False
        if enviar_alerta and ESMALTES_KITS_MONITOR_ALERTA_RESUMO and pode_alertar:
            msg = montar_mensagem_telegram(
                consolidado,
                resultados,
                serie=serie,
                deltas=deltas,
                agir=batalha_out.get("agir") if isinstance(batalha_out, dict) else None,
            )
            chave = chave_resumo_periodo("esmaltes:kits_monitor", horas_por_bucket=6)
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave,
                    cooldown_segundos=ESMALTES_KITS_MONITOR_ALERTA_COOLDOWN_SEG,
                    agente_id="monitor_kits_esmaltes",
                )
            )
            grafico = grafico_evolucao(
                serie, _SERIES_CAMPOS, GRAFICO_PATH, titulo="Kits esmaltes — evolução"
            )
            if grafico:
                enviar_foto_gestor(
                    str(grafico),
                    "📊 Kits esmaltes — evolução vs rodadas anteriores",
                    chave=f"{chave}:grafico",
                    cooldown_segundos=ESMALTES_KITS_MONITOR_ALERTA_COOLDOWN_SEG,
                )

        gauge("esmaltes.kits.total_unicos", float(consolidado.get("total_kits_unicos") or 0))
        gauge("esmaltes.kits.total_vendas", float(consolidado.get("total_vendas") or 0))
        incrementar("esmaltes.kits.rodadas")

        return {
            "ok": True,
            "total_termos": len(resultados),
            "consolidado": consolidado,
            "deltas": deltas,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
            "batalha_impala": {
                "anuncios_unicos": (batalha_out.get("batalha") or {}).get("anuncios_unicos"),
                "sellers_unicos": (batalha_out.get("batalha") or {}).get("sellers_unicos"),
                "agir_criticas": (batalha_out.get("agir") or {}).get("criticas"),
            },
        }
    except Exception as exc:
        logger.error("Agente kits esmaltes erro: %s", exc)
        incrementar("esmaltes.kits.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor kits esmaltes ML — radar de mercado")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Monitor kits esmaltes ML ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    c = out.get("consolidado") or {}
    logger.info(
        "Concluído: %s termo(s), %s kit(s) únicos, vendas_proxy=%s, alerta=%s",
        out.get("total_termos"),
        c.get("total_kits_unicos"),
        c.get("total_vendas"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
