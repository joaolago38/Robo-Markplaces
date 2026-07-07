"""
agentes/esmaltes/agente_monitor_kits_esmaltes.py
Monitora todos os anúncios de kits de esmaltes no ML: vendas, valores e marcas líderes.

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
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.esmaltes.analise_kits_esmaltes import consolidar_varredura, processar_termo
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_kits_esmaltes")

SNAPSHOT_PATH = ROOT / "logs" / "esmaltes_kits_monitor_ultima.json"
HISTORY_PATH = ROOT / "logs" / "esmaltes_kits_monitor_history.json"


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


def montar_mensagem_telegram(
    consolidado: dict[str, Any],
    resultados: list[dict[str, Any]],
) -> str:
    linhas = [
        "🎨 *Kits esmaltes ML — vendas e marcas*",
        "",
        f"Kits únicos: *{consolidado.get('total_kits_unicos', 0)}* | "
        f"Vendas (proxy ML): *{consolidado.get('total_vendas', 0):,}*".replace(",", "."),
        f"Preços: {_fmt_brl(consolidado.get('preco_min'))} – "
        f"{_fmt_brl(consolidado.get('preco_max'))} | média {_fmt_brl(consolidado.get('preco_medio'))}",
        f"Termos varridos: {consolidado.get('termos_varridos', 0)}",
        "",
        "*Marcas que mais vendem*",
    ]

    ranking = consolidado.get("ranking_marcas") or []
    if ranking:
        for item in ranking[:8]:
            linhas.append(
                f"• {item.get('marca', '?')}: {item.get('vendidos', 0)} vendas | "
                f"{item.get('anuncios', 0)} anúncio(s) | média {_fmt_brl(item.get('preco_medio'))}"
            )
    else:
        linhas.append("_Nenhuma marca com vendas registradas nesta rodada._")

    padroes = consolidado.get("padroes_tamanho") or []
    if padroes:
        linhas.extend(["", "*Por tamanho de kit*"])
        for p in padroes[:6]:
            linhas.append(
                f"• Kit {p.get('qtd')}: {p.get('anuncios', 0)} anúncio(s) | "
                f"{p.get('vendidos', 0)} vendas | média {_fmt_brl(p.get('preco_medio'))}"
            )

    top = consolidado.get("top_vendas") or []
    if top:
        linhas.extend(["", "*Top anúncios (vendas)*"])
        for i, an in enumerate(top[:10], 1):
            titulo = str(an.get("titulo") or "?")[:55]
            linhas.append(
                f"{i}. {titulo} — {_fmt_brl(an.get('preco'))} | "
                f"{int(an.get('quantidade_vendida') or 0)} vendas | {an.get('marca', '?')}"
            )

    linhas.extend(["", "*Varredura por termo*"])
    for r in resultados:
        if not r.get("ok"):
            continue
        linhas.append(
            f"• {r.get('nome', '?')}: `{r.get('termo_busca', '')}` → "
            f"{r.get('total_kits', 0)} kit(s) de {r.get('total_bruto', 0)} anúncio(s)"
        )

    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas kits esmaltes não serão entregues")

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
            anuncios = ml_client.buscar_concorrentes_por_termo(termo, limite=limite)
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

        escrever_json_atomico(
            SNAPSHOT_PATH,
            {"timestamp": agora, "consolidado": consolidado, "resultados": resultados},
        )

        historico = ler_json(HISTORY_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}
        historico["ultima_varredura"] = agora
        historico["total_kits_unicos"] = consolidado.get("total_kits_unicos")
        historico["total_vendas"] = consolidado.get("total_vendas")
        historico["lider_marca"] = (consolidado.get("ranking_marcas") or [{}])[0].get("marca")
        escrever_json_atomico(HISTORY_PATH, historico)

        alerta_enviado = False
        if enviar_alerta and ESMALTES_KITS_MONITOR_ALERTA_RESUMO and consolidado.get("total_kits_unicos", 0) >= 0:
            msg = montar_mensagem_telegram(consolidado, resultados)
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_resumo_periodo("esmaltes:kits_monitor", horas_por_bucket=6),
                    cooldown_segundos=ESMALTES_KITS_MONITOR_ALERTA_COOLDOWN_SEG,
                )
            )

        gauge("esmaltes.kits.total_unicos", float(consolidado.get("total_kits_unicos") or 0))
        gauge("esmaltes.kits.total_vendas", float(consolidado.get("total_vendas") or 0))
        incrementar("esmaltes.kits.rodadas")

        return {
            "ok": True,
            "total_termos": len(resultados),
            "consolidado": consolidado,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente kits esmaltes erro: %s", exc)
        incrementar("esmaltes.kits.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor kits esmaltes ML — vendas e marcas")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Monitor kits esmaltes ML ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    c = out.get("consolidado") or {}
    logger.info(
        "Concluído: %s termo(s), %s kit(s) únicos, %s vendas, alerta=%s",
        out.get("total_termos"),
        c.get("total_kits_unicos"),
        c.get("total_vendas"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
