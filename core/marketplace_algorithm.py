"""
core/marketplace_algorithm.py
Avalia saúde por marketplace e define ajustes de algoritmo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from core.config import MARKETPLACE_VARIACAO_ALERTA_PCT

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


def _calc_variacao_pct(atual: float, anterior: float | None) -> float | None:
    if anterior is None:
        return None
    if anterior == 0:
        return 100.0 if atual > 0 else 0.0
    return ((atual - anterior) / abs(anterior)) * 100


def _detectar_variacoes_relevantes(metrics: dict, ponto_anterior: dict | None) -> list[dict]:
    if not ponto_anterior:
        return []

    anterior_metrics = ponto_anterior.get("metrics", {})
    limite = float(MARKETPLACE_VARIACAO_ALERTA_PCT)
    checks = [
        ("score", float(ponto_anterior.get("score", 0)), float(metrics.get("score_atual", 0))),
        ("pendencias", float(anterior_metrics.get("pendencias", 0)), float(metrics.get("pendencias", 0))),
        ("claims_rate", float(anterior_metrics.get("claims_rate", 0)), float(metrics.get("claims_rate", 0))),
    ]

    variacoes = []
    for nome, anterior, atual in checks:
        variacao_pct = _calc_variacao_pct(atual, anterior)
        if variacao_pct is None:
            continue
        if abs(variacao_pct) >= limite:
            variacoes.append(
                {
                    "metrica": nome,
                    "anterior": round(anterior, 4),
                    "atual": round(atual, 4),
                    "variacao_pct": round(variacao_pct, 2),
                }
            )
    return variacoes


def _ajustes_finos_vendas(variacoes: list[dict], score_atual: int) -> list[str]:
    acoes = []
    for v in variacoes:
        if v["metrica"] == "score" and v["variacao_pct"] <= -5:
            acoes.append("Queda de performance: reduzir preço em 1-2% nos SKUs mais disputados por 24h.")
        elif v["metrica"] == "pendencias" and v["variacao_pct"] >= 5:
            acoes.append("Fila subiu: priorizar respostas e pós-venda para recuperar conversão.")
        elif v["metrica"] == "claims_rate" and v["variacao_pct"] >= 5:
            acoes.append("Reclamação em alta: revisar descrição/oferta e prazo para reduzir atrito.")

    if score_atual >= 85 and not acoes:
        acoes.append("Performance estável: testar aumento fino de preço em 1% nos produtos com melhor giro.")
    return list(dict.fromkeys(acoes))


def _ajustes_recomendados(metrics: dict, score_atual: int, media_historica: float | None, variacoes: list[dict]) -> list[str]:
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

    for ajuste in _ajustes_finos_vendas(variacoes, score_atual):
        acoes.append(ajuste)

    if not acoes:
        acoes.append("manter estratégia atual e seguir monitoramento")
    return acoes


def avaliar_marketplace(nome: str, metrics: dict) -> dict:
    historico = _load_history()
    pontos = historico.get(nome, [])

    score_atual, penalidades = _score_from_metrics(metrics)
    metrics_com_score = {**metrics, "score_atual": score_atual}
    media_historica = None
    if pontos:
        media_historica = sum(p.get("score", 0) for p in pontos[-10:]) / min(len(pontos), 10)
    ponto_anterior = pontos[-1] if pontos else None
    variacoes = _detectar_variacoes_relevantes(metrics_com_score, ponto_anterior)

    avaliacao = {
        "marketplace": nome,
        "score": score_atual,
        "status": _classificar(score_atual),
        "penalidades": penalidades,
        "variacoes_relevantes": variacoes,
        "acoes_recomendadas": _ajustes_recomendados(metrics, score_atual, media_historica, variacoes),
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
