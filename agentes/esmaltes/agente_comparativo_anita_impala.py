"""
agentes/esmaltes/agente_comparativo_anita_impala.py
Comparativo Anita vs Impala no ML: demanda, perfil de consumidor e plano para vencer.

Catálogo: catalogo/anita_impala_comparativo_segmentos.json

Uso:
  python -m agentes.esmaltes.agente_comparativo_anita_impala
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
    ANITA_ESMALTES_CATALOGO,
    COMPARATIVO_ESMALTES_ALERTA_COOLDOWN_SEG,
    COMPARATIVO_ESMALTES_ALERTA_RESUMO,
    COMPARATIVO_ESMALTES_CATALOGO,
    COMPARATIVO_ESMALTES_PAUSA_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.esmaltes.comparativo_anita_impala import (
    comparar_segmento,
    consolidar_comparativo,
    enriquecer_com_sinais_proprios,
    gerar_estrategias_vencer,
    label_perfil,
)
from integracoes.marketplaces.sinais_comprador import coletar_sinais
from integracoes.ml import ml_client

logger = logging.getLogger("agente_comparativo_anita_impala")

HISTORY_PATH = ROOT / "logs" / "anita_impala_comparativo_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "anita_impala_comparativo_ultima.json"


def _carregar_segmentos() -> list[dict[str, Any]]:
    caminho = ROOT / COMPARATIVO_ESMALTES_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        return [s for s in data if isinstance(s, dict) and s.get("ativo")]
    except Exception as exc:
        logger.error("Erro ao carregar catálogo comparativo: %s", exc)
        return []


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _coletar_sinais_referencia() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sinais_anita: list[dict[str, Any]] = []
    sinais_impala: list[dict[str, Any]] = []

    anita_cat = ler_json(ROOT / ANITA_ESMALTES_CATALOGO, default=[])
    if isinstance(anita_cat, list):
        for p in anita_cat[:4]:
            if not isinstance(p, dict) or not p.get("ativo"):
                continue
            termo = str(p.get("termo_busca") or "")
            sinais_anita.append(
                coletar_sinais(
                    "mercadolivre",
                    {"termo_busca": termo, "item_id": p.get("item_id") or ""},
                    sku=str(p.get("id") or "anita"),
                    termo_busca=termo,
                )
            )

    for prod in carregar_produtos_para_operacao(merge_bling=False)[:6]:
        sku = str(prod.get("sku") or "")
        if "IMP" not in sku.upper():
            continue
        canais = prod.get("canais") or {}
        ml = canais.get("mercadolivre") or {}
        termo = str(ml.get("termo_busca") or prod.get("termo_busca") or "")
        sinais_impala.append(
            coletar_sinais(
                "mercadolivre",
                ml,
                sku=sku,
                termo_busca=termo,
            )
        )

    return sinais_anita, sinais_impala


def _montar_painel(consolidado: dict[str, Any], estrategias: list[dict[str, Any]]) -> str:
    proxy = bool(consolidado.get("volume_eh_proxy"))
    fonte = consolidado.get("fonte_volume") or "anuncios"
    unidade = {"vendas": "un.", "avaliacoes": "aval.", "anuncios": "anúncios"}.get(fonte, "un.")
    if not proxy:
        unidade = "un."
    linhas = [
        "⚖️ *Anita vs Impala — desempenho e consumidor (ML)*",
        "",
        "_Volume = vendas da API; se vier zerado, usa avaliações ou nº de anúncios._",
        "",
        "*Resumo global*",
        f"  • Anita: *{consolidado.get('anita_unidades_vendidas', 0)}* {unidade} "
        f"({consolidado.get('anita_share_pct', 0):.0f}% share)",
        f"  • Impala: *{consolidado.get('impala_unidades_vendidas', 0)}* {unidade} "
        f"({consolidado.get('impala_share_pct', 0):.0f}% share)",
        f"  • Líder: *{consolidado.get('vencedor_global', '?')}* "
        f"(dif. {consolidado.get('diferenca_unidades', 0):+d})",
        f"  • Segmentos: Anita {consolidado.get('segmentos_anita_lider', 0)} | "
        f"Impala {consolidado.get('segmentos_impala_lider', 0)}",
    ]
    if proxy:
        linhas.append(
            f"  _Volume via proxy (*{fonte}*) — API não retornou sold_quantity._"
        )
    linhas.append("")

    perfis_a = consolidado.get("perfis_anita_global") or []
    perfis_i = consolidado.get("perfis_impala_global") or []
    if perfis_a or perfis_i:
        linhas.append("*Quem compra (perfil inferido do anúncio)*")
        if perfis_i:
            p = perfis_i[0]
            linhas.append(
                f"  • Impala → {label_perfil(p['perfil'])} ({p['peso_vendas']} un. ponderadas)"
            )
        if perfis_a:
            p = perfis_a[0]
            linhas.append(
                f"  • Anita → {label_perfil(p['perfil'])} ({p['peso_vendas']} un. ponderadas)"
            )
        linhas.append("")

    linhas.append("*Por segmento*")
    for r in sorted(consolidado.get("resultados") or [], key=lambda x: int(x.get("prioridade") or 99)):
        anita = r.get("anita") or {}
        impala = r.get("impala") or {}
        linhas.append(
            f"  *{r.get('nome', r.get('id'))}* — líder: {r.get('vencedor_vendas')} "
            f"(A:{anita.get('unidades_vendidas', 0)} vs I:{impala.get('unidades_vendidas', 0)})"
        )
        if anita.get("preco_por_unidade_medio") or impala.get("preco_por_unidade_medio"):
            linhas.append(
                f"    Preço/un: Anita {_fmt_brl(anita.get('preco_por_unidade_medio'))} | "
                f"Impala {_fmt_brl(impala.get('preco_por_unidade_medio'))}"
            )

    sinais = consolidado.get("sinais_proprios") or {}
    visitas_a = sum(int(s.get("visitas_7d") or 0) for s in sinais.get("anita") or [])
    visitas_i = sum(int(s.get("visitas_7d") or 0) for s in sinais.get("impala") or [])
    if visitas_a or visitas_i:
        linhas.extend(
            [
                "",
                "*Seus anúncios (visitas 7d)*",
                f"  Anita: {visitas_a} visitas | Impala: {visitas_i} visitas",
            ]
        )

    if estrategias:
        linhas.extend(["", "*Como vencer a diferença*"])
        for e in estrategias[:6]:
            emoji = "🔴" if e.get("prioridade") == "alta" else "🟡"
            linhas.append(f"  {emoji} {e.get('titulo')}: {e.get('texto')}")

    return "\n".join(linhas).strip()


def _analisar_segmento(segmento: dict[str, Any]) -> dict[str, Any]:
    termo = str(segmento.get("termo_busca") or "").strip()
    limite = int(segmento.get("limite_resultados") or 20)
    if not termo:
        return {"id": segmento.get("id"), "ok": False, "motivo": "termo vazio"}

    item_ref = str(segmento.get("item_id_referencia") or segmento.get("item_id_ml") or "").strip() or None
    anuncios = ml_client.buscar_concorrentes_por_termo(
        termo,
        limite=limite,
        item_id_referencia=item_ref,
    )
    out = comparar_segmento(segmento, anuncios)
    out["prioridade"] = int(segmento.get("prioridade") or 99)
    fontes = sorted({str(a.get("fonte_busca") or "") for a in anuncios if a.get("fonte_busca")})
    out["fonte_busca"] = fontes[0] if len(fontes) == 1 else ("misto" if fontes else "nenhuma")

    sid = str(segmento.get("id") or "")
    gauge(
        "comparativo_esmaltes.unidades_anita",
        float((out.get("anita") or {}).get("unidades_vendidas") or 0),
        tags=[f"segmento:{sid}"],
    )
    gauge(
        "comparativo_esmaltes.unidades_impala",
        float((out.get("impala") or {}).get("unidades_vendidas") or 0),
        tags=[f"segmento:{sid}"],
    )
    logger.info(
        "Comparativo %s: Anita %s vs Impala %s — líder %s (fonte %s)",
        segmento.get("nome"),
        (out.get("anita") or {}).get("unidades_vendidas"),
        (out.get("impala") or {}).get("unidades_vendidas"),
        out.get("vencedor_vendas"),
        out.get("fonte_busca"),
    )
    return out


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — comparativo não alertará")

        segmentos = sorted(_carregar_segmentos(), key=lambda s: int(s.get("prioridade") or 99))
        if not segmentos:
            return {"ok": True, "total_segmentos": 0, "resultados": []}

        resultados: list[dict[str, Any]] = []
        for i, seg in enumerate(segmentos):
            if i > 0 and COMPARATIVO_ESMALTES_PAUSA_SEG > 0:
                time.sleep(COMPARATIVO_ESMALTES_PAUSA_SEG)
            resultados.append(_analisar_segmento(seg))

        consolidado = consolidar_comparativo(resultados)
        sinais_anita, sinais_impala = _coletar_sinais_referencia()
        enriquecer_com_sinais_proprios(
            consolidado,
            sinais_anita=sinais_anita,
            sinais_impala=sinais_impala,
        )
        estrategias = gerar_estrategias_vencer(consolidado)

        agora = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "timestamp": agora,
            "consolidado": consolidado,
            "estrategias": estrategias,
            "resultados": resultados,
        }
        escrever_json_atomico(SNAPSHOT_PATH, snapshot)

        historico = ler_json(HISTORY_PATH, default={})
        historico["ultima_varredura"] = agora
        historico["anita_share_pct"] = consolidado.get("anita_share_pct")
        historico["impala_share_pct"] = consolidado.get("impala_share_pct")
        historico["vencedor_global"] = consolidado.get("vencedor_global")
        historico["diferenca_unidades"] = consolidado.get("diferenca_unidades")
        escrever_json_atomico(HISTORY_PATH, historico)

        gauge("comparativo_esmaltes.anita_share", float(consolidado.get("anita_share_pct") or 0))
        gauge("comparativo_esmaltes.impala_share", float(consolidado.get("impala_share_pct") or 0))

        alerta_enviado = False
        if enviar_alerta and COMPARATIVO_ESMALTES_ALERTA_RESUMO and consolidado.get("segmentos_com_dados"):
            painel = _montar_painel(consolidado, estrategias)
            alerta_enviado = bool(
                alertar_gestor(
                    painel,
                    chave=chave_resumo_periodo("esmaltes:anita_impala", horas_por_bucket=4),
                    cooldown_segundos=COMPARATIVO_ESMALTES_ALERTA_COOLDOWN_SEG,
                )
            )

        incrementar("comparativo_esmaltes.rodadas", tags=[f"segmentos:{len(resultados)}"])
        return {
            "ok": True,
            "total_segmentos": len(resultados),
            "consolidado": consolidado,
            "estrategias": estrategias,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Comparativo Anita/Impala erro: %s", exc)
        incrementar("comparativo_esmaltes.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Comparativo Anita vs Impala no ML")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Comparativo Anita vs Impala ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    c = out.get("consolidado") or {}
    logger.info(
        "Concluído: Anita %s%% vs Impala %s%%, alerta=%s",
        c.get("anita_share_pct"),
        c.get("impala_share_pct"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
