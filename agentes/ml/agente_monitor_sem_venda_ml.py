"""
agentes/ml/agente_monitor_sem_venda_ml.py
Lista anúncios próprios no ML sem venda no período e alerta no Telegram.

Uso:
  python -m agentes.ml.agente_monitor_sem_venda_ml
  python -m agentes.ml.agente_monitor_sem_venda_ml --sem-envio --dias 30
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import (
    MONITOR_SEM_VENDA_ALERTA_RESUMO,
    MONITOR_SEM_VENDA_COOLDOWN_SEG,
    MONITOR_SEM_VENDA_DIAS,
    MONITOR_SEM_VENDA_MAX_ITENS,
    MONITOR_SEM_VENDA_VISITAS_ALTAS,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from core.telegram_explicacao import inserir_explicacao
from integracoes.ml.analise_sem_venda import analisar_anuncios_sem_venda, montar_mensagem_sem_venda
from integracoes.ml.ml_client import buscar_metricas_item, listar_meus_anuncios, listar_pedidos_detalhado

logger = logging.getLogger("agente_monitor_sem_venda_ml")

SNAPSHOT_PATH = ROOT / "logs" / "sem_venda_ml_ultima.json"


def _item_ids_com_venda(dias: int) -> set[str]:
    pedidos, ok = listar_pedidos_detalhado(dias=dias)
    if not ok:
        logger.warning("sem_venda: busca de pedidos falhou — análise parcial")
    ids: set[str] = set()
    for pedido in pedidos or []:
        for item in pedido.get("itens") or []:
            iid = str(item.get("item_id") or "").strip()
            if iid:
                ids.add(iid)
    return ids


def _coletar_metricas(item_ids: list[str], limite: int) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item_id in item_ids[: max(0, limite)]:
        m = buscar_metricas_item(item_id)
        if m:
            out[item_id] = m
    return out


def executar(
    *,
    enviar_alerta: bool = True,
    dias: int | None = None,
) -> dict[str, Any]:
    """Monitora anúncios sem venda. Nunca lança."""
    try:
        janela = int(dias if dias is not None else MONITOR_SEM_VENDA_DIAS)
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — sem_venda sem envio")

        anuncios = listar_meus_anuncios()
        vendidos = _item_ids_com_venda(janela)
        candidatos = [
            str(a.get("item_id") or "").strip()
            for a in anuncios
            if str(a.get("item_id") or "").strip()
            and str(a.get("item_id") or "").strip() not in vendidos
            and "PREENCHER" not in str(a.get("item_id") or "").upper()
        ]
        metricas = _coletar_metricas(candidatos, MONITOR_SEM_VENDA_MAX_ITENS)
        analise = analisar_anuncios_sem_venda(
            anuncios,
            vendidos,
            metricas,
            dias=janela,
            visitas_altas=MONITOR_SEM_VENDA_VISITAS_ALTAS,
            max_itens=MONITOR_SEM_VENDA_MAX_ITENS,
        )

        try:
            gauge("ml.sem_venda.total", float(analise.get("total_sem_venda") or 0))
            gauge("ml.sem_venda.anuncios_ativos", float(analise.get("total_anuncios") or 0))
            if analise.get("total_sem_venda"):
                incrementar("ml.sem_venda.alertas", 1.0)
        except Exception:
            pass

        enviado = False
        if (
            enviar_alerta
            and MONITOR_SEM_VENDA_ALERTA_RESUMO
            and int(analise.get("total_sem_venda") or 0) > 0
        ):
            enviado = bool(
                alertar_gestor(
                    inserir_explicacao(
                        montar_mensagem_sem_venda(analise),
                        "monitor_sem_venda_ml",
                    ),
                    chave=chave_resumo_periodo(
                        "sem_venda_ml",
                        horas_por_bucket=max(1, MONITOR_SEM_VENDA_COOLDOWN_SEG // 3600),
                    ),
                    cooldown_segundos=MONITOR_SEM_VENDA_COOLDOWN_SEG,
                    agente_id="monitor_sem_venda_ml",
                )
            )

        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "enviado": enviado,
            **analise,
        }
        try:
            escrever_json_atomico(SNAPSHOT_PATH, snapshot)
        except Exception as exc:
            logger.warning("snapshot sem_venda: %s", exc)

        return {
            "ok": True,
            "enviado": enviado,
            "dias": janela,
            "total_anuncios": analise.get("total_anuncios", 0),
            "total_com_venda": analise.get("total_com_venda", 0),
            "total_sem_venda": analise.get("total_sem_venda", 0),
            "por_acao": analise.get("por_acao") or {},
            "itens": analise.get("itens") or [],
        }
    except Exception as exc:
        logger.error("executar sem_venda: %s", exc)
        return {"ok": False, "erro": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor anúncios ML sem venda")
    parser.add_argument("--sem-envio", action="store_true")
    parser.add_argument("--dias", type=int, default=None)
    args = parser.parse_args(argv)
    out = executar(enviar_alerta=not args.sem_envio, dias=args.dias)
    print(json.dumps({k: v for k, v in out.items() if k != "itens"}, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
