"""
core/marketplace_algorithm.py
Avalia saúde por marketplace e define ajustes de algoritmo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
HISTORY_FILE = ROOT / "logs" / "marketplace_algorithm_history.json"


def _load_history() -> dict:
    if not HISTORY_FILE.exists():
        return {}
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_history(history: dict) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _score_from_metrics(metrics: dict) -> tuple[int, list[str]]:
    penalidades = []
    score = 100

    if not metrics.get("configurado", False):
        return 0, ["configuração ausente para este marketplace"]

    pendencias = int(metrics.get("pendencias", 0) or 0)
    claims_rate = float(metrics.get("claims_rate", 0) or 0)
    dias_sem_acesso = int(metrics.get("dias_sem_acesso", 0) or 0)

    if pendencias >= 40:
        score -= 35
        penalidades.append(f"fila de pendências muito alta ({pendencias})")
    elif pendencias >= 15:
        score -= 20
        penalidades.append(f"fila de pendências elevada ({pendencias})")
    elif pendencias >= 5:
        score -= 8
        penalidades.append(f"fila de pendências moderada ({pendencias})")

    if claims_rate >= 0.02:
        score -= 30
        penalidades.append(f"taxa de reclamação alta ({claims_rate * 100:.2f}%)")
    elif claims_rate >= 0.01:
        score -= 15
        penalidades.append(f"taxa de reclamação em atenção ({claims_rate * 100:.2f}%)")

    if dias_sem_acesso >= 7:
        score -= 25
        penalidades.append(f"{dias_sem_acesso} dias sem acesso")
    elif dias_sem_acesso >= 3:
        score -= 12
        penalidades.append(f"{dias_sem_acesso} dias sem acesso")

    return max(0, min(100, score)), penalidades


def _classificar(score: int) -> str:
    if score >= 80:
        return "saudavel"
    if score >= 60:
        return "atencao"
    return "critico"


def _ajustes_recomendados(metrics: dict, score_atual: int, media_historica: float | None) -> list[str]:
    acoes = []
    pendencias = int(metrics.get("pendencias", 0) or 0)
    claims_rate = float(metrics.get("claims_rate", 0) or 0)
    dias_sem_acesso = int(metrics.get("dias_sem_acesso", 0) or 0)

    if dias_sem_acesso >= 2:
        acoes.append("executar keepalive imediato e validar token")
    if pendencias >= 15:
        acoes.append("priorizar respostas de perguntas/mensagens nas próximas 2h")
    if claims_rate >= 0.01:
        acoes.append("reduzir promessas nos anúncios e revisar SLAs para conter reclamações")
    if score_atual < 60:
        acoes.append("reduzir mudanças agressivas de preço por 24h e estabilizar atendimento")

    if media_historica is not None and (media_historica - score_atual) >= 15:
        acoes.append("queda brusca detectada: revisar títulos, preço e estoque imediatamente")

    if not acoes:
        acoes.append("manter estratégia atual e seguir monitoramento")
    return acoes


def avaliar_marketplace(nome: str, metrics: dict) -> dict:
    historico = _load_history()
    pontos = historico.get(nome, [])

    score_atual, penalidades = _score_from_metrics(metrics)
    media_historica = None
    if pontos:
        media_historica = sum(p.get("score", 0) for p in pontos[-10:]) / min(len(pontos), 10)

    avaliacao = {
        "marketplace": nome,
        "score": score_atual,
        "status": _classificar(score_atual),
        "penalidades": penalidades,
        "acoes_recomendadas": _ajustes_recomendados(metrics, score_atual, media_historica),
        "metrics": metrics,
        "media_historica": round(media_historica, 1) if media_historica is not None else None,
    }

    pontos.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "score": score_atual,
        "metrics": metrics,
    })
    historico[nome] = pontos[-100:]
    _save_history(historico)

    return avaliacao
