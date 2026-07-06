"""
agentes/esmaltes/agente_monitor_busca_kit_esmaltes.py
Monitora quantas buscas por dia são feitas para kits de esmaltes Anita e Impala no ML,
com análise de cores nos anúncios retornados. Envia resumo no Telegram.

Catálogo: catalogo/esmaltes_busca_kit_frequencia.json

Uso:
  python -m agentes.esmaltes.agente_monitor_busca_kit_esmaltes
  python -m agentes.esmaltes.agente_monitor_busca_kit_esmaltes --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    ESMALTES_BUSCA_KIT_ALERTA_COOLDOWN_SEG,
    ESMALTES_BUSCA_KIT_ALERTA_RESUMO,
    ESMALTES_BUSCA_KIT_CATALOGO,
    ESMALTES_BUSCA_KIT_PAUSA_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.esmaltes.busca_kit_frequencia import (
    consolidar_dia,
    executar_busca_item,
    registrar_execucao_diaria,
)
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_busca_kit_esmaltes")

HISTORY_PATH = ROOT / "logs" / "esmaltes_busca_kit_frequencia_diario.json"
SNAPSHOT_PATH = ROOT / "logs" / "esmaltes_busca_kit_ultima.json"


def _carregar_itens() -> list[dict[str, Any]]:
    caminho = ROOT / ESMALTES_BUSCA_KIT_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        ativos = [i for i in data if isinstance(i, dict) and i.get("ativo")]
        return sorted(ativos, key=lambda x: (str(x.get("marca") or ""), int(x.get("prioridade") or 99)))
    except Exception as exc:
        logger.error("Erro ao carregar catálogo busca kit: %s", exc)
        return []


def _chave_dia_local() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def _formatar_cores(cores: dict[str, int]) -> str:
    if not cores:
        return "nenhuma cor mapeada"
    partes = sorted(cores.items(), key=lambda x: x[1], reverse=True)
    return ", ".join(f"{c} ({q})" for c, q in partes[:5])


def montar_mensagem_telegram(
    dia: str,
    dia_obj: dict[str, Any],
    consolidado: dict[str, Any],
    rodada: list[dict[str, Any]],
) -> str:
    linhas = [
        "🔍 *Busca kit esmaltes — frequência diária*",
        f"Data: {dia}",
        "",
        f"Buscas hoje: *{consolidado.get('total_buscas', 0)}* "
        f"(Anita {consolidado.get('anita', 0)} | Impala {consolidado.get('impala', 0)})",
        f"Itens monitorados: {consolidado.get('itens_distintos', 0)}",
        "",
        "*Última rodada*",
    ]
    for r in rodada:
        if not r.get("ok"):
            continue
        marca = str(r.get("marca") or "?").title()
        linhas.append(
            f"• [{marca}] {r.get('nome', '?')} — cor foco: {r.get('cor_foco', '?')}"
        )
        linhas.append(
            f"  `{r.get('termo_busca', '')}` → {r.get('total_anuncios', 0)} anúncios "
            f"({r.get('anuncios_da_marca', 0)} da marca)"
        )
        linhas.append(f"  Cores: {_formatar_cores(r.get('cores_encontradas') or {})}")

    linhas.extend(["", "*Acumulado do dia por kit*"])
    itens = dia_obj.get("itens") or {}
    for item_id, reg in sorted(itens.items(), key=lambda x: int(x[1].get("buscas") or 0), reverse=True):
        marca = str(reg.get("marca") or "?").title()
        linhas.append(
            f"• {marca} — {reg.get('nome', item_id)} ({reg.get('cor_foco', '?')}): "
            f"{reg.get('buscas', 0)} busca(s), {reg.get('total_anuncios_acum', 0)} anúncios"
        )
        linhas.append(f"  Cores: {_formatar_cores(reg.get('cores_encontradas') or {})}")

    top = consolidado.get("top_cores") or []
    if top:
        linhas.append("")
        linhas.append("*Top cores no dia (menções em títulos)*")
        linhas.append(", ".join(f"{t['cor']} ({t['mencoes']})" for t in top[:6]))

    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas não serão entregues")

        itens = _carregar_itens()
        if not itens:
            return {"ok": True, "total_itens": 0, "buscas_hoje": 0}

        historico = ler_json(HISTORY_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}

        dia = _chave_dia_local()
        agora = datetime.now(timezone.utc).isoformat()
        resultados_rodada: list[dict[str, Any]] = []

        for item in itens:
            termo = str(item.get("termo_busca") or "").strip()
            limite = int(item.get("limite_resultados") or 20)
            logger.info("Busca kit esmaltes [%s]: %s", item.get("marca"), termo)
            item_ref = str(item.get("item_id_ml") or item.get("item_id_referencia") or "").strip() or None
            anuncios = ml_client.buscar_concorrentes_por_termo(
                termo,
                limite=limite,
                item_id_referencia=item_ref,
            )
            resultado = executar_busca_item(item, anuncios, timestamp=agora)
            resultados_rodada.append(resultado)
            registrar_execucao_diaria(historico, resultado, dia=dia)
            incrementar(
                "esmaltes.busca_kit",
                tags=[f"marca:{item.get('marca', '?')}", f"item:{item.get('id', '?')}"],
            )
            gauge(
                "esmaltes.busca_kit.anuncios",
                float(resultado.get("total_anuncios") or 0),
                tags=[f"marca:{item.get('marca', '?')}"],
            )
            time.sleep(ESMALTES_BUSCA_KIT_PAUSA_SEG)

        escrever_json_atomico(HISTORY_PATH, historico)
        dia_obj = historico.get(dia) or {}
        consolidado = consolidar_dia(dia_obj)

        escrever_json_atomico(
            SNAPSHOT_PATH,
            {
                "timestamp": agora,
                "dia": dia,
                "consolidado": consolidado,
                "rodada": resultados_rodada,
                "historico_dia": dia_obj,
            },
        )

        alerta_enviado = False
        if enviar_alerta and ESMALTES_BUSCA_KIT_ALERTA_RESUMO:
            msg = montar_mensagem_telegram(dia, dia_obj, consolidado, resultados_rodada)
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_resumo_periodo(f"esmaltes:busca_kit:{dia}", horas_por_bucket=24),
                    cooldown_segundos=ESMALTES_BUSCA_KIT_ALERTA_COOLDOWN_SEG,
                )
            )

        return {
            "ok": True,
            "dia": dia,
            "total_itens": len(itens),
            "buscas_rodada": len(resultados_rodada),
            "buscas_hoje": consolidado.get("total_buscas", 0),
            "consolidado": consolidado,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados_rodada,
        }
    except Exception as exc:
        logger.error("Agente busca kit esmaltes erro: %s", exc)
        return {"ok": False, "erro": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor busca kit esmaltes Anita/Impala + cores")
    parser.add_argument("--sem-alerta", action="store_true", help="Não envia Telegram")
    args = parser.parse_args(argv)

    logger.info("=== Monitor busca kit esmaltes Anita/Impala ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    logger.info(
        "Concluído: %s item(ns), buscas hoje=%s, alerta=%s",
        out.get("total_itens"),
        out.get("buscas_hoje"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
