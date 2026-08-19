"""
agentes/social/agente_metricas_meta.py
Valida campanhas Meta (Instagram/Facebook) e gera alertas/recomendações.
"""
import logging
from datetime import datetime, timezone

from core.atomic_io import escrever_json_atomico
from core.config import (
    META_CPC_MAXIMO,
    META_CTR_MINIMO,
    META_FREQ_MAXIMA,
    META_GASTO_MINIMO_ALERTA,
    META_ROAS_MINIMO,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor
from integracoes.meta.ciclo_campanhas import (
    agregar_meta_campanhas,
    avaliar_eficiencia_ciclo,
    emitir_metricas_ciclo_meta,
)
from integracoes.meta.meta_ads_client import (
    listar_metricas_campanhas,
    listar_metricas_por_plataforma,
    normalizar_metrica_campanha,
    normalizar_por_plataforma,
)
from integracoes.social.sustentabilidade_ads_ml import coletar_receita_ml

logger = logging.getLogger("agente_metricas_meta")
HEARTBEAT_PATH = ROOT / "logs" / "meta_metricas_ultima.json"


def _heartbeat(payload: dict, datadog_ok: bool) -> None:
    """Snapshot para o Vigia (best-effort). Escreve mesmo com Meta Ads sem token."""
    try:
        resumo = payload.get("resumo") if isinstance(payload.get("resumo"), dict) else {}
        ciclo = payload.get("ciclo") if isinstance(payload.get("ciclo"), dict) else {}
        escrever_json_atomico(
            HEARTBEAT_PATH,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": bool(datadog_ok),
                "campanhas": int(resumo.get("total") or 0),
                "pronto": bool(ciclo.get("pronto")) if ciclo else None,
            },
        )
    except Exception as exc:
        logger.warning("Meta heartbeat: %s", exc)


def _avaliar_campanha(c: dict) -> dict:
    score = 100
    motivos = []
    recomendacoes = []

    if c["cpc"] > META_CPC_MAXIMO:
        score -= 20
        motivos.append(f"CPC alto ({c['cpc']:.2f})")
        recomendacoes.append("Revisar segmentação e criativos para reduzir CPC.")
    if c["ctr"] < META_CTR_MINIMO:
        score -= 25
        motivos.append(f"CTR baixo ({c['ctr']:.2f}%)")
        recomendacoes.append("Testar novos criativos e chamadas para ação.")
    if c["roas"] < META_ROAS_MINIMO and c["gasto"] >= META_GASTO_MINIMO_ALERTA:
        score -= 30
        motivos.append(f"ROAS baixo ({c['roas']:.2f}) com gasto relevante")
        recomendacoes.append("Ajustar público, oferta e página de destino.")
    if c["frequencia"] > META_FREQ_MAXIMA:
        score -= 15
        motivos.append(f"Frequência alta ({c['frequencia']:.2f})")
        recomendacoes.append("Rotacionar criativos para reduzir fadiga do anúncio.")

    score = max(0, score)
    if score < 60:
        status = "critico"
    elif score < 80:
        status = "atencao"
    else:
        status = "saudavel"

    if not recomendacoes:
        recomendacoes.append("Manter campanha e monitorar próximas 24h.")

    return {
        "id": c["id"],
        "nome": c["nome"],
        "status": status,
        "score": score,
        "motivos": motivos,
        "recomendacoes": recomendacoes[:3],
        "metricas": c,
    }


def executar(alertar_quando_atencao: bool = False, periodo_dias: int = 1) -> dict:
    rows = listar_metricas_campanhas(periodo_dias=periodo_dias)
    campanhas = [_avaliar_campanha(normalizar_metrica_campanha(row)) for row in rows]

    for c in campanhas:
        if c["status"] == "critico" or (alertar_quando_atencao and c["status"] == "atencao"):
            alertar_gestor(
                f"Meta Ads {c['status'].upper()}: {c['nome']} (score {c['score']})\n"
                f"Motivos: {'; '.join(c['motivos'][:2])}\n"
                f"Ação: {'; '.join(c['recomendacoes'][:2])}"
            )

    resumo = {
        "total": len(campanhas),
        "saudavel": sum(1 for c in campanhas if c["status"] == "saudavel"),
        "atencao": sum(1 for c in campanhas if c["status"] == "atencao"),
        "critico": sum(1 for c in campanhas if c["status"] == "critico"),
    }
    payload = {"resumo": resumo, "campanhas": campanhas}
    datadog_ok = False
    try:
        incrementar("meta.rodadas")
        gauge("meta.campanhas_total", float(resumo["total"]))
        gauge("meta.campanhas_critico", float(resumo["critico"]))
        gauge("meta.campanhas_atencao", float(resumo["atencao"]))
        gastos = [float((c.get("metricas") or {}).get("gasto") or 0) for c in campanhas]
        roas_vals = [float((c.get("metricas") or {}).get("roas") or 0) for c in campanhas]
        gauge("meta.gasto_total", float(sum(gastos)))
        if roas_vals:
            gauge("meta.roas_medio", float(sum(roas_vals) / len(roas_vals)))
        if resumo["critico"]:
            incrementar("meta.alerta_critico", float(resumo["critico"]))
        plat_rows = listar_metricas_por_plataforma(periodo_dias=periodo_dias)
        efic = avaliar_eficiencia_ciclo(
            meta=agregar_meta_campanhas(campanhas),
            ml=coletar_receita_ml(periodo_dias),
            periodo_dias=periodo_dias,
        )
        momento = emitir_metricas_ciclo_meta(
            plataformas=normalizar_por_plataforma(plat_rows),
            eficiencia=efic,
        )
        if isinstance(momento, dict):
            payload["ciclo"] = {
                "pronto": bool(momento.get("pronto")),
                "saude_conta_ok": bool(momento.get("saude_conta_ok")),
                "impala_ok": bool(momento.get("impala_ok")),
                "fase": momento.get("fase"),
                "motivo": momento.get("motivo"),
                "eficiencia": momento.get("eficiencia"),
            }
        datadog_ok = True
    except Exception as exc:
        logger.warning("Meta metricas Datadog: %s", exc)
    _heartbeat(payload, datadog_ok)
    logger.info("Métricas Meta: %s", payload)
    return payload


if __name__ == "__main__":
    print(executar(alertar_quando_atencao=False, periodo_dias=1))
