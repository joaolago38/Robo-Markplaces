"""
agentes/vendas/agente_monitor_margem_vendas.py
Monitora margem de lucro das vendas em ML / Shopee / Magalu / Amazon e alerta no Telegram.

Uso:
  python -m agentes.vendas.agente_monitor_margem_vendas
  python -m agentes.vendas.agente_monitor_margem_vendas --sem-envio
  python -m agentes.vendas.agente_monitor_margem_vendas --dias 3
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, lock_exclusivo
from core.config import (
    MONITOR_MARGEM_VENDAS_ALERTA_BAIXA,
    MONITOR_MARGEM_VENDAS_ALERTA_RESUMO,
    MONITOR_MARGEM_VENDAS_DIAS,
    MONITOR_MARGEM_VENDAS_MARGEM_MIN_PCT,
    MONITOR_MARGEM_VENDAS_RESUMO_COOLDOWN_SEG,
    ROOT,
    SPEC,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import (
    alertar_critico,
    alertar_gestor,
    chave_resumo_periodo,
    gestor_telegram_configurado,
)
from core.telegram_explicacao import inserir_explicacao
from integracoes.vendas.analise_margem_vendas import (
    analisar_pedidos,
    montar_mensagem_alerta_baixa,
    montar_mensagem_resumo,
)

logger = logging.getLogger("agente_monitor_margem_vendas")

SNAPSHOT_PATH = ROOT / "logs" / "margem_vendas_ultima.json"
ALERTADAS_PATH = ROOT / "dados" / "margem_vendas_alertadas.json"
_LOCK_PATH = ALERTADAS_PATH.with_name(ALERTADAS_PATH.name + ".lock")

_MARKETPLACES_ATIVOS: set[str] = {
    m["id"] for m in SPEC.get("marketplaces", []) if m.get("ativo", False)
}


def _carregar_alertadas() -> set[str]:
    try:
        ALERTADAS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if ALERTADAS_PATH.is_file():
            data = json.loads(ALERTADAS_PATH.read_text(encoding="utf-8"))
            return set(data.get("alertadas") or [])
    except Exception as exc:
        logger.error("Erro ao carregar margem_vendas_alertadas: %s", exc)
    return set()


def _salvar_alertadas(ids: set[str]) -> None:
    try:
        lista = sorted(ids)[-2000:]
        escrever_json_atomico(ALERTADAS_PATH, {"alertadas": lista})
    except Exception as exc:
        logger.error("Erro ao salvar margem_vendas_alertadas: %s", exc)


def _buscar_pedidos(dias: int) -> tuple[dict[str, list[dict]], dict[str, bool]]:
    """Retorna pedidos por marketplace e mapa de sucesso da API."""
    pedidos: dict[str, list[dict]] = {}
    ok_map: dict[str, bool] = {}

    fontes: list[tuple[str, str, Any]] = [
        ("mercadolivre", "Mercado Livre", "integracoes.ml.ml_client"),
        ("shopee", "Shopee", "integracoes.shopee.shopee_client"),
        ("amazon", "Amazon", "integracoes.amazon.amazon_client"),
    ]
    if "magalu" in _MARKETPLACES_ATIVOS:
        fontes.append(("magalu", "Magalu", "integracoes.magalu.magalu_client"))

    for mp_id, nome, modulo in fontes:
        try:
            import importlib

            client = importlib.import_module(modulo)
            lista, ok = client.listar_pedidos_detalhado(dias=dias)
            pedidos[mp_id] = lista if ok else []
            ok_map[mp_id] = bool(ok)
            if not ok:
                logger.error("%s: busca de pedidos FALHOU no monitor de margem", nome)
                alertar_critico(
                    f"⚠️ Margem vendas: não consegui buscar pedidos no {nome}.\n"
                    "Vendas desse canal podem estar sem monitoramento de lucro.",
                    chave=f"margem_vendas_falha_pedidos:{mp_id}",
                )
        except Exception as exc:
            logger.error("Erro ao buscar pedidos %s: %s", mp_id, exc)
            pedidos[mp_id] = []
            ok_map[mp_id] = False

    return pedidos, ok_map


def _carregar_produtos() -> list[dict[str, Any]]:
    try:
        from core.catalogo_produtos import carregar_produtos_para_operacao

        return carregar_produtos_para_operacao(merge_bling=True)
    except Exception as exc:
        logger.warning("Catálogo/Bling indisponível — só JSON local: %s", exc)
        try:
            from core.catalogo_produtos import carregar_produtos_catalogo

            return carregar_produtos_catalogo()
        except Exception as exc2:
            logger.error("Falha ao carregar catálogo: %s", exc2)
            return []


def _emitir_metricas(analise: dict[str, Any]) -> None:
    try:
        gauge("vendas.margem_media_pct", float(analise.get("margem_media_pct") or 0))
        gauge("vendas.lucro_reais", float(analise.get("lucro_reais") or 0))
        gauge("vendas.receita_bruta", float(analise.get("receita_bruta") or 0))
        incrementar("vendas.itens_analisados", float(analise.get("total_itens") or 0))
        if analise.get("total_alertas"):
            incrementar("vendas.alertas_margem_baixa", float(analise["total_alertas"]))
    except Exception as exc:
        logger.debug("métricas margem: %s", exc)


def executar(
    *,
    enviar_alerta: bool = True,
    dias: int | None = None,
    margem_min_pct: float | None = None,
) -> dict[str, Any]:
    """Analisa margem das vendas recentes e notifica no Telegram. Nunca lança."""
    try:
        janela = int(dias if dias is not None else MONITOR_MARGEM_VENDAS_DIAS)
        min_pct = float(
            margem_min_pct
            if margem_min_pct is not None
            else MONITOR_MARGEM_VENDAS_MARGEM_MIN_PCT
        )

        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — monitor margem sem envio")

        pedidos, ok_map = _buscar_pedidos(janela)
        produtos = _carregar_produtos()
        analise = analisar_pedidos(pedidos, produtos, margem_min_pct=min_pct)
        _emitir_metricas(analise)

        alertas_enviados = 0
        resumo_enviado = False

        with lock_exclusivo(_LOCK_PATH):
            ja = _carregar_alertadas()
            novas_chaves: set[str] = set()

            if enviar_alerta and MONITOR_MARGEM_VENDAS_ALERTA_BAIXA:
                for linha in analise.get("alertas") or []:
                    chave = str(linha.get("chave") or "")
                    if not chave or chave in ja:
                        continue
                    msg = inserir_explicacao(
                        montar_mensagem_alerta_baixa(linha, margem_min_pct=min_pct),
                        "monitor_margem_vendas",
                    )
                    ok = alertar_gestor(
                        msg,
                        chave=f"margem_baixa:{chave}",
                        cooldown_segundos=86400,
                        agente_id="monitor_margem_vendas",
                    )
                    if ok:
                        alertas_enviados += 1
                        novas_chaves.add(chave)

            if (
                enviar_alerta
                and MONITOR_MARGEM_VENDAS_ALERTA_RESUMO
                and int(analise.get("total_itens") or 0) > 0
            ):
                resumo_enviado = bool(
                    alertar_gestor(
                        inserir_explicacao(
                            montar_mensagem_resumo(analise, dias=janela),
                            "monitor_margem_vendas",
                        ),
                        chave=chave_resumo_periodo("margem_vendas", horas_por_bucket=max(1, MONITOR_MARGEM_VENDAS_RESUMO_COOLDOWN_SEG // 3600)),
                        cooldown_segundos=MONITOR_MARGEM_VENDAS_RESUMO_COOLDOWN_SEG,
                        agente_id="monitor_margem_vendas",
                    )
                )

            if novas_chaves:
                _salvar_alertadas(ja | novas_chaves)

        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dias": janela,
            "margem_min_pct": min_pct,
            "apis_ok": ok_map,
            "alertas_enviados": alertas_enviados,
            "resumo_enviado": resumo_enviado,
            "analise": {
                k: v
                for k, v in analise.items()
                if k not in {"linhas"}  # snapshot enxuto; linhas no detalhe abaixo
            },
            "linhas": analise.get("linhas") or [],
        }
        try:
            escrever_json_atomico(SNAPSHOT_PATH, snapshot)
        except Exception as exc:
            logger.warning("snapshot margem: %s", exc)

        return {
            "ok": True,
            "dias": janela,
            "margem_min_pct": min_pct,
            "total_itens": analise.get("total_itens", 0),
            "total_alertas": analise.get("total_alertas", 0),
            "total_incompletos": analise.get("total_incompletos", 0),
            "receita_bruta": analise.get("receita_bruta", 0),
            "lucro_reais": analise.get("lucro_reais", 0),
            "margem_media_pct": analise.get("margem_media_pct", 0),
            "alertas_enviados": alertas_enviados,
            "resumo_enviado": resumo_enviado,
            "apis_ok": ok_map,
            "por_marketplace": analise.get("por_marketplace") or {},
        }
    except Exception as exc:
        logger.error("executar monitor margem: %s", exc)
        return {"ok": False, "erro": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor de margem das vendas (Telegram)")
    parser.add_argument("--sem-envio", action="store_true", help="Não envia Telegram")
    parser.add_argument("--dias", type=int, default=None, help="Janela de pedidos")
    parser.add_argument(
        "--margem-min",
        type=float,
        default=None,
        help="Margem mínima %% (default: config)",
    )
    args = parser.parse_args(argv)
    out = executar(
        enviar_alerta=not args.sem_envio,
        dias=args.dias,
        margem_min_pct=args.margem_min,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
