"""
agentes/ml/agente_relatorio_estrategia_ml.py
Relatório de estratégia de vendas no ML: top ações a partir do monitor + loja concorrente.

Uso:
  python -m agentes.ml.agente_relatorio_estrategia_ml
  python -m agentes.ml.agente_relatorio_estrategia_ml --sem-coleta
  python -m agentes.ml.agente_relatorio_estrategia_ml --sem-envio
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import (
    ESTRATEGIA_ML_COOLDOWN_SEG,
    ESTRATEGIA_ML_GAP_GUERRA_PCT,
    ESTRATEGIA_ML_MAX_ACOES,
    ROOT,
)
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.ml.estrategia_vendas_ml import gerar_acoes_estrategia, montar_mensagem_estrategia

logger = logging.getLogger("agente_relatorio_estrategia_ml")

SNAPSHOT_PATH = ROOT / "logs" / "relatorio_estrategia_ml_ultima.json"
LOJA_SNAPSHOT = ROOT / "logs" / "analise_loja_novamix_ultima.json"


def _carregar_json(path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Falha ao ler %s: %s", path, exc)
        return {}


def _coletar_monitor() -> dict[str, Any]:
    from agentes.ml.agente_monitor_concorrentes import executar as executar_concorrentes

    # Sem reviews por anúncio — só preço/gap (bem mais rápido para o relatório)
    return executar_concorrentes(enviar_alerta=False, enriquecer_metricas=False)


def _coletar_loja() -> dict[str, Any]:
    from integracoes.ml.analise_loja_concorrente import analisar_loja

    # Novamix padrão; se houver outras lojas no JSON, o monitor já cobre ameacas
    out = analisar_loja(
        "1666381510",
        nickname="NOVAMIX_COMERCIAL",
        enriquecer_metricas=False,
    )
    try:
        escrever_json_atomico(
            LOJA_SNAPSHOT,
            {"timestamp": datetime.now(timezone.utc).isoformat(), **out},
        )
    except Exception as exc:
        logger.warning("snapshot loja: %s", exc)
    return out


def executar(
    *,
    enviar_alerta: bool = True,
    coletar_fresco: bool = True,
) -> dict[str, Any]:
    """Gera relatório de ações. Nunca lança."""
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — relatório estratégia sem envio")

        monitor: dict[str, Any]
        analise_loja: dict[str, Any]

        if coletar_fresco:
            logger.info("Estratégia ML: coletando monitor + loja...")
            monitor = _coletar_monitor()
            analise_loja = _coletar_loja()
        else:
            logger.info("Estratégia ML: usando snapshots em logs/")
            hist = _carregar_json(ROOT / "logs" / "concorrentes_ml_history.json")
            # reconstrói resultados mínimos a partir do histórico + catálogo monitor
            monitor = {"ok": True, "resultados": [], "alertas": []}
            try:
                from agentes.ml.agente_monitor_concorrentes import _carregar_lista

                for entrada in _carregar_lista():
                    if not entrada.get("ativo"):
                        continue
                    eid = str(entrada.get("id") or "")
                    h = hist.get(eid) if isinstance(hist.get(eid), dict) else {}
                    monitor["resultados"].append(
                        {
                            "id": eid,
                            "ok": True,
                            "tipo": str(entrada.get("tipo") or "termo"),
                            "nome": entrada.get("nome") or eid,
                            "sku": entrada.get("sku") or "",
                            "seller_id": entrada.get("seller_id") or "",
                            "nickname": entrada.get("nickname") or h.get("nickname"),
                            "meu_preco": float(entrada.get("meu_preco") or h.get("meu_preco") or 0),
                            "menor_preco": float(h.get("menor_preco") or 0),
                            "ameacas_preco": [],
                        }
                    )
            except Exception as exc:
                logger.warning("reconstruir monitor: %s", exc)
            analise_loja = _carregar_json(LOJA_SNAPSHOT)

        try:
            from core.catalogo_produtos import carregar_produtos_para_operacao

            produtos = carregar_produtos_para_operacao(merge_bling=False)
        except Exception:
            from core.catalogo_produtos import carregar_produtos_catalogo

            produtos = carregar_produtos_catalogo()

        estrategia = gerar_acoes_estrategia(
            monitor=monitor,
            analise_loja=analise_loja,
            produtos=produtos,
            gap_guerra_pct=ESTRATEGIA_ML_GAP_GUERRA_PCT,
            max_acoes=ESTRATEGIA_ML_MAX_ACOES,
        )
        relatorio = montar_mensagem_estrategia(estrategia)

        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ok": True,
            "coletar_fresco": coletar_fresco,
            "acoes": estrategia.get("acoes") or [],
            "contexto": estrategia.get("contexto") or {},
            "relatorio": relatorio,
            "monitor_ok": bool(monitor.get("ok")),
            "loja_anuncios": int(analise_loja.get("total_anuncios_coletados") or 0),
        }
        escrever_json_atomico(SNAPSHOT_PATH, snapshot)

        enviado = False
        if enviar_alerta and gestor_telegram_configurado():
            chave = chave_resumo_periodo("relatorio:estrategia_ml", horas_por_bucket=24)
            enviado = bool(
                alertar_gestor(
                    relatorio,
                    chave=chave,
                    cooldown_segundos=ESTRATEGIA_ML_COOLDOWN_SEG,
                )
            )

        incrementar(
            "ml.relatorio_estrategia.rodadas",
            tags=["ok:true", f"acoes:{len(snapshot['acoes'])}"],
        )
        logger.info(
            "Estratégia ML: %s ações, enviado=%s",
            len(snapshot["acoes"]),
            enviado,
        )
        return {
            "ok": True,
            "acoes": snapshot["acoes"],
            "relatorio": relatorio,
            "alerta_enviado": enviado,
            "snapshot": str(SNAPSHOT_PATH),
        }
    except Exception as exc:
        logger.error("Relatório estratégia ML erro: %s", exc)
        incrementar("ml.relatorio_estrategia.rodadas", tags=["ok:false"])
        return {"ok": False, "erro": str(exc), "acoes": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Relatório estratégia de vendas ML")
    parser.add_argument("--sem-envio", action="store_true")
    parser.add_argument(
        "--sem-coleta",
        action="store_true",
        help="Usa só logs/snapshots (não chama monitor/loja ao vivo)",
    )
    args = parser.parse_args(argv)
    logger.info("=== Relatório estratégia ML ===")
    out = executar(enviar_alerta=not args.sem_envio, coletar_fresco=not args.sem_coleta)
    if out.get("relatorio"):
        print(out["relatorio"])
    if not out.get("ok"):
        logger.error("Falha: %s", out.get("erro"))
        return 1
    print(f"\nSnapshot: {out.get('snapshot')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
