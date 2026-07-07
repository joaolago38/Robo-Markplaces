"""
agentes/esmaltes/agente_monitor_removedores_unha.py
Monitora removedores de unha no ML: nomes, fabricantes e ranking por vendas.

Catálogo: catalogo/removedores_unha_monitor.json

Uso:
  python -m agentes.esmaltes.agente_monitor_removedores_unha
  python -m agentes.esmaltes.agente_monitor_removedores_unha --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    REMOVEDORES_UNHA_ALERTA_COOLDOWN_SEG,
    REMOVEDORES_UNHA_ALERTA_RESUMO,
    REMOVEDORES_UNHA_CATALOGO,
    REMOVEDORES_UNHA_PAUSA_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.esmaltes.analise_removedores import consolidar_varredura, processar_termo
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_removedores_unha")

SNAPSHOT_PATH = ROOT / "logs" / "removedores_unha_ultima.json"
HISTORY_PATH = ROOT / "logs" / "removedores_unha_history.json"

_MEDALHAS = ("🥇", "🥈", "🥉")


def _carregar_termos() -> list[dict[str, Any]]:
    caminho = ROOT / REMOVEDORES_UNHA_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        ativos = [t for t in data if isinstance(t, dict) and t.get("ativo")]
        return sorted(ativos, key=lambda x: int(x.get("prioridade") or 99))
    except Exception as exc:
        logger.error("Erro ao carregar catálogo removedores: %s", exc)
        return []


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _medalha(posicao: int) -> str:
    if 1 <= posicao <= len(_MEDALHAS):
        return _MEDALHAS[posicao - 1]
    return f"{posicao}."


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


def montar_mensagem_telegram(
    consolidado: dict[str, Any],
    resultados: list[dict[str, Any]],
) -> str:
    linhas = [
        "💅 *Removedores de unha ML — ranking*",
        "",
        f"Produtos únicos: *{consolidado.get('total_produtos_unicos', 0)}* | "
        f"Vendas (proxy ML): *{consolidado.get('total_vendas', 0):,}*".replace(",", "."),
        f"Preços: {_fmt_brl(consolidado.get('preco_min'))} – "
        f"{_fmt_brl(consolidado.get('preco_max'))} | média {_fmt_brl(consolidado.get('preco_medio'))}",
        "",
        "*Ranking por fabricante (vendas)*",
    ]

    ranking = consolidado.get("ranking_fabricantes") or []
    if ranking:
        for item in ranking[:10]:
            pos = int(item.get("rank") or 0)
            linhas.append(
                f"{_medalha(pos)} *{item.get('fabricante', '?')}* — "
                f"{item.get('vendidos', 0)} vendas | "
                f"{item.get('anuncios', 0)} anúncio(s) | média {_fmt_brl(item.get('preco_medio'))}"
            )
    else:
        linhas.append("_Nenhum fabricante com vendas nesta rodada._")

    top = consolidado.get("top_vendas") or []
    if top:
        linhas.extend(["", "*Produtos mais vendidos*"])
        for p in top[:12]:
            pos = int(p.get("rank_vendas") or 0)
            nome = str(p.get("nome_produto") or p.get("titulo") or "?")[:60]
            fab = p.get("fabricante") or p.get("marca") or "?"
            vol = p.get("volume_ml")
            vol_txt = f" | {vol}ml" if vol else ""
            linhas.append(
                f"{_medalha(pos)} {nome}\n"
                f"   🏭 {fab}{vol_txt} — {_fmt_brl(p.get('preco'))} | "
                f"{int(p.get('quantidade_vendida') or 0)} vendas"
            )

    linhas.extend(["", "*Varredura por termo*"])
    for r in resultados:
        if not r.get("ok"):
            continue
        linhas.append(
            f"• {r.get('nome', '?')}: `{r.get('termo_busca', '')}` → "
            f"{r.get('total_removedores', 0)} removedor(es)"
        )

    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas removedores não serão entregues")

        termos = _carregar_termos()
        if not termos:
            return {"ok": True, "total_termos": 0, "consolidado": {}}

        agora = datetime.now(timezone.utc).isoformat()
        resultados: list[dict[str, Any]] = []

        for i, segmento in enumerate(termos):
            logger.info("Varredura removedores: %s", segmento.get("termo_busca"))
            anuncios = _buscar_anuncios(segmento)
            resultado = processar_termo(segmento, anuncios)
            resultados.append(resultado)

            gauge(
                "esmaltes.removedores.anuncios",
                float(resultado.get("total_removedores") or 0),
                tags=[f"termo:{segmento.get('id', '?')}"],
            )
            incrementar("esmaltes.removedores.varreduras", tags=[f"termo:{segmento.get('id', '?')}"])

            if i < len(termos) - 1 and REMOVEDORES_UNHA_PAUSA_SEG > 0:
                time.sleep(REMOVEDORES_UNHA_PAUSA_SEG)

        consolidado = consolidar_varredura(resultados)

        escrever_json_atomico(
            SNAPSHOT_PATH,
            {"timestamp": agora, "consolidado": consolidado, "resultados": resultados},
        )

        historico = ler_json(HISTORY_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}
        ranking = consolidado.get("ranking_fabricantes") or []
        historico["ultima_varredura"] = agora
        historico["total_produtos"] = consolidado.get("total_produtos_unicos")
        historico["total_vendas"] = consolidado.get("total_vendas")
        historico["lider_fabricante"] = ranking[0].get("fabricante") if ranking else None
        escrever_json_atomico(HISTORY_PATH, historico)

        alerta_enviado = False
        if enviar_alerta and REMOVEDORES_UNHA_ALERTA_RESUMO:
            msg = montar_mensagem_telegram(consolidado, resultados)
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_resumo_periodo("esmaltes:removedores", horas_por_bucket=6),
                    cooldown_segundos=REMOVEDORES_UNHA_ALERTA_COOLDOWN_SEG,
                )
            )

        gauge("esmaltes.removedores.total", float(consolidado.get("total_produtos_unicos") or 0))
        gauge("esmaltes.removedores.vendas", float(consolidado.get("total_vendas") or 0))
        incrementar("esmaltes.removedores.rodadas")

        return {
            "ok": True,
            "total_termos": len(resultados),
            "consolidado": consolidado,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente removedores unha erro: %s", exc)
        incrementar("esmaltes.removedores.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor removedores de unha ML")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Monitor removedores de unha ML ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    c = out.get("consolidado") or {}
    logger.info(
        "Concluído: %s termo(s), %s produto(s), %s vendas, alerta=%s",
        out.get("total_termos"),
        c.get("total_produtos_unicos"),
        c.get("total_vendas"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
