"""
agentes/filamentos/agente_monitor_filamentos_ml.py
Monitora filamentos 3D no Mercado Livre: preços, cores, marcas e cruzamento Alibaba.

Catálogo ML: catalogo/filamentos_3d_monitor.json
Catálogo Alibaba: catalogo/alibaba_produtos_importacao.json (itens filamento)

Uso:
  python -m agentes.filamentos.agente_monitor_filamentos_ml
  python -m agentes.filamentos.agente_monitor_filamentos_ml --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    FILAMENTOS_ML_ALERTA_COOLDOWN_SEG,
    FILAMENTOS_ML_ALERTA_RESUMO,
    FILAMENTOS_ML_ALIBABA_MAX_CORES,
    FILAMENTOS_ML_ALIBABA_PAUSA_SEG,
    FILAMENTOS_ML_CATALOGO,
    FILAMENTOS_ML_CRUZAR_ALIBABA,
    FILAMENTOS_ML_PAUSA_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.graficos import grafico_evolucao
from core.notificador import alertar_gestor, chave_resumo_periodo, enviar_foto_gestor, gestor_telegram_configurado
from core.series_historica import formatar_comparativo, registrar_ponto
from integracoes.filamentos.analise_filamentos_ml import consolidar_varredura, processar_termo
from integracoes.filamentos.cruzamento_alibaba import cruzar_filamentos_ml_alibaba, formatar_secao_cruzamento
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_filamentos_ml")

SNAPSHOT_PATH = ROOT / "logs" / "filamentos_ml_ultima.json"
HISTORY_PATH = ROOT / "logs" / "filamentos_ml_history.json"
SERIES_PATH = ROOT / "logs" / "filamentos_ml_series.json"
GRAFICO_PATH = ROOT / "logs" / "filamentos_ml_grafico.png"

_SERIES_CAMPOS = [
    ("total_filamentos", "Filamentos únicos"),
    ("total_vendas", "Vendas (proxy)"),
    ("preco_medio", "Preço médio"),
]


def _carregar_termos() -> list[dict[str, Any]]:
    caminho = ROOT / FILAMENTOS_ML_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        ativos = [t for t in data if isinstance(t, dict) and t.get("ativo")]
        return sorted(ativos, key=lambda x: int(x.get("prioridade") or 99))
    except Exception as exc:
        logger.error("Erro ao carregar catálogo filamentos ML: %s", exc)
        return []


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return "n/d"
    if v <= 0:
        return "n/d"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def montar_mensagem_telegram(
    consolidado: dict[str, Any],
    resultados: list[dict[str, Any]],
    *,
    serie: list[dict[str, Any]] | None = None,
    cruzamento: dict[str, Any] | None = None,
) -> str:
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente(
            "monitor_filamentos_ml",
            "🧵 *Filamentos 3D — ML × Alibaba*",
        ),
        "",
        f"Anúncios únicos: *{consolidado.get('total_filamentos_unicos', 0)}* | "
        f"Vendas (proxy): *{consolidado.get('total_vendas', 0):,}*".replace(",", "."),
        f"Preços: {_fmt_brl(consolidado.get('preco_min'))} – "
        f"{_fmt_brl(consolidado.get('preco_max'))} | média {_fmt_brl(consolidado.get('preco_medio'))}",
        f"Termos varridos: {consolidado.get('termos_varridos', 0)}",
    ]
    if serie:
        comp = formatar_comparativo(
            serie,
            [
                ("total_filamentos", "Anúncios"),
                ("total_vendas", "Vendas"),
                ("preco_medio", "Preço médio", 2),
            ],
        )
        if comp:
            linhas.extend(["", comp])

    cores = consolidado.get("ranking_cores") or []
    linhas.extend(["", "*Cores mais vendidas (ML)*"])
    if cores:
        for item in cores[:8]:
            linhas.append(
                f"• {item.get('cor', '?')}: {item.get('vendidos', 0)} vendas | "
                f"{item.get('anuncios', 0)} anúncio(s) | média {_fmt_brl(item.get('preco_medio'))}"
            )
    else:
        linhas.append("_Nenhuma cor detectada nos títulos nesta rodada._")

    ranking = consolidado.get("ranking_marcas") or []
    linhas.extend(["", "*Marcas que mais vendem*"])
    if ranking:
        for item in ranking[:8]:
            linhas.append(
                f"• {item.get('marca', '?')}: {item.get('vendidos', 0)} vendas | "
                f"{item.get('anuncios', 0)} anúncio(s) | média {_fmt_brl(item.get('preco_medio'))}"
            )
    else:
        linhas.append("_Nenhuma marca com vendas nesta rodada._")

    mats = consolidado.get("ranking_materiais") or []
    if mats:
        linhas.extend(["", "*Por material*"])
        for item in mats[:6]:
            linhas.append(
                f"• {item.get('material', '?')}: {item.get('anuncios', 0)} anúncio(s) | "
                f"{item.get('vendidos', 0)} vendas | média {_fmt_brl(item.get('preco_medio'))}"
            )

    baratos = consolidado.get("top_baratos") or []
    if baratos:
        linhas.extend(["", "*Mais baratos (1kg proxy)*"])
        for an in baratos[:5]:
            titulo = str(an.get("titulo") or "?")[:50]
            cor = an.get("cor") or "?"
            linhas.append(
                f"• {_fmt_brl(an.get('preco'))} — {titulo} ({an.get('marca', '?')}, {cor})"
            )

    top = consolidado.get("top_vendas") or []
    if top:
        linhas.extend(["", "*Top anúncios (vendas)*"])
        for i, an in enumerate(top[:8], 1):
            titulo = str(an.get("titulo") or "?")[:55]
            linhas.append(
                f"{i}. {titulo} — {_fmt_brl(an.get('preco'))} | "
                f"{int(an.get('quantidade_vendida') or 0)} vendas | "
                f"{an.get('marca', '?')} | {an.get('cor', '?')}"
            )

    if cruzamento is not None:
        linhas.extend(formatar_secao_cruzamento(cruzamento, fmt_brl=_fmt_brl))

    linhas.extend(["", "*Por termo*"])
    for r in resultados:
        if not r.get("ok"):
            continue
        linhas.append(
            f"• {r.get('nome', '?')}: {_fmt_brl(r.get('preco_min'))}–{_fmt_brl(r.get('preco_max'))} "
            f"(média {_fmt_brl(r.get('preco_medio'))}) | "
            f"{r.get('total_filamentos', 0)} de {r.get('total_bruto', 0)} anúncio(s)"
        )

    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas filamentos ML não serão entregues")

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
            logger.info("Varredura filamentos ML: %s", termo)
            anuncios = ml_client.buscar_concorrentes_por_termo(termo, limite=limite)
            resultado = processar_termo(segmento, anuncios)
            resultados.append(resultado)

            gauge(
                "filamentos.ml.anuncios",
                float(resultado.get("total_filamentos") or 0),
                tags=[f"termo:{segmento.get('id', '?')}"],
            )
            incrementar("filamentos.ml.varreduras", tags=[f"termo:{segmento.get('id', '?')}"])

            if i < len(termos) - 1 and FILAMENTOS_ML_PAUSA_SEG > 0:
                time.sleep(FILAMENTOS_ML_PAUSA_SEG)

        consolidado = consolidar_varredura(resultados)

        cruzamento: dict[str, Any] | None = None
        if FILAMENTOS_ML_CRUZAR_ALIBABA:
            logger.info(
                "Cruzando ML × Alibaba (top %s cores)",
                FILAMENTOS_ML_ALIBABA_MAX_CORES,
            )
            cruzamento = cruzar_filamentos_ml_alibaba(
                consolidado,
                resultados,
                max_cores=FILAMENTOS_ML_ALIBABA_MAX_CORES,
                pausa_seg=FILAMENTOS_ML_ALIBABA_PAUSA_SEG,
            )
            gauge(
                "filamentos.ml.alibaba_ofertas",
                float(
                    sum(
                        int(c.get("total_oportunidades_alibaba") or 0)
                        for c in (cruzamento.get("cruzamentos") or [])
                    )
                ),
            )
            gauge("filamentos.ml.alibaba_lucrativos", float(cruzamento.get("lucrativos") or 0))

        escrever_json_atomico(
            SNAPSHOT_PATH,
            {
                "timestamp": agora,
                "consolidado": consolidado,
                "resultados": resultados,
                "cruzamento_alibaba": cruzamento,
            },
        )

        serie = registrar_ponto(
            SERIES_PATH,
            {
                "ts": agora,
                "total_filamentos": consolidado.get("total_filamentos_unicos") or 0,
                "total_vendas": consolidado.get("total_vendas") or 0,
                "preco_medio": consolidado.get("preco_medio") or 0,
            },
        )

        historico = ler_json(HISTORY_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}
        historico["ultima_varredura"] = agora
        historico["total_filamentos_unicos"] = consolidado.get("total_filamentos_unicos")
        historico["total_vendas"] = consolidado.get("total_vendas")
        historico["lider_marca"] = (consolidado.get("ranking_marcas") or [{}])[0].get("marca")
        historico["lider_cor"] = (consolidado.get("ranking_cores") or [{}])[0].get("cor")
        if cruzamento:
            historico["alibaba_lucrativos"] = cruzamento.get("lucrativos")
        escrever_json_atomico(HISTORY_PATH, historico)

        alerta_enviado = False
        if enviar_alerta and FILAMENTOS_ML_ALERTA_RESUMO and gestor_telegram_configurado():
            msg = montar_mensagem_telegram(
                consolidado, resultados, serie=serie, cruzamento=cruzamento
            )
            chave = chave_resumo_periodo("filamentos:ml_monitor", horas_por_bucket=6)
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave,
                    cooldown_segundos=FILAMENTOS_ML_ALERTA_COOLDOWN_SEG,
                    agente_id="monitor_filamentos_ml",
                )
            )
            grafico = grafico_evolucao(
                serie, _SERIES_CAMPOS, GRAFICO_PATH, titulo="Filamentos 3D ML — evolução"
            )
            if grafico:
                enviar_foto_gestor(
                    str(grafico),
                    "📊 Filamentos 3D ML — evolução vs rodadas anteriores",
                    chave=f"{chave}:grafico",
                    cooldown_segundos=FILAMENTOS_ML_ALERTA_COOLDOWN_SEG,
                )

        gauge("filamentos.ml.total_unicos", float(consolidado.get("total_filamentos_unicos") or 0))
        gauge("filamentos.ml.total_vendas", float(consolidado.get("total_vendas") or 0))
        incrementar("filamentos.ml.rodadas")

        return {
            "ok": True,
            "total_termos": len(resultados),
            "consolidado": consolidado,
            "cruzamento_alibaba": cruzamento,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente filamentos ML erro: %s", exc)
        incrementar("filamentos.ml.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor filamentos 3D ML × Alibaba")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Monitor filamentos 3D ML × Alibaba ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    c = out.get("consolidado") or {}
    cruz = out.get("cruzamento_alibaba") or {}
    logger.info(
        "Concluído: %s termo(s), %s anúncio(s), cor líder=%s, alibaba lucrativos=%s, alerta=%s",
        out.get("total_termos"),
        c.get("total_filamentos_unicos"),
        (c.get("ranking_cores") or [{}])[0].get("cor"),
        cruz.get("lucrativos"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
