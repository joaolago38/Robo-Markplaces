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


def _perfil(nome: str) -> str:
    n = (nome or "").strip().lower()
    if n in ("mercadolivre", "shopee", "magalu", "amazon"):
        return n
    return "generico"


def _claims_conhecido(metrics: dict) -> bool:
    if "claims_conhecido" in metrics:
        return bool(metrics.get("claims_conhecido"))
    return metrics.get("claims_rate") is not None


def _score_from_metrics(metrics: dict, nome: str = "") -> tuple[int, list[str], str | None]:
    """Retorna (score, penalidades, status_forcado).

    status_forcado='inativo' quando o canal não está configurado — não é
    incidente de algoritmo; alerta/Telegram ficam suspensos até ativar.

    Perfil por canal:
      ML — fila, claims reais, acesso (ranking + reputação).
      Shopee — chat/SLA mais pesado; claims só se medido.
      Magalu — fila + SLA; claims só se medido.
      Amazon — fila de mensagens pesa pouco (Buy Box ≠ Q&A); claims só se medido.
    """
    penalidades = []
    score = 100
    perfil = _perfil(nome)

    if not metrics.get("configurado", False):
        return 0, ["canal não configurado — alerta suspenso até ativar"], "inativo"

    if metrics.get("api_ok") is False:
        return 65, ["falha na API de saúde (credenciais presentes; verifique token/conectividade)"], None

    pendencias = int(metrics.get("pendencias", 0) or 0)
    claims_rate = metrics.get("claims_rate")
    try:
        claims_val = float(claims_rate) if claims_rate is not None else 0.0
    except (TypeError, ValueError):
        claims_val = 0.0
    dias_sem_acesso = int(metrics.get("dias_sem_acesso", 0) or 0)

    if perfil == "shopee":
        if pendencias >= 25:
            score -= 40
            penalidades.append(f"chat Shopee parado ({pendencias}) — ranking pune resposta lenta")
        elif pendencias >= 10:
            score -= 22
            penalidades.append(f"fila de chat Shopee elevada ({pendencias})")
        elif pendencias >= 3:
            score -= 10
            penalidades.append(f"chat Shopee com {pendencias} pendência(s)")
    elif perfil == "amazon":
        if pendencias >= 40:
            score -= 15
            penalidades.append(f"mensagens Amazon sem resposta ({pendencias}) — não é Buy Box")
        elif pendencias >= 15:
            score -= 8
            penalidades.append(f"fila de mensagens Amazon ({pendencias})")
    else:
        if pendencias >= 40:
            score -= 35
            penalidades.append(f"fila de pendências muito alta ({pendencias})")
        elif pendencias >= 15:
            score -= 20
            penalidades.append(f"fila de pendências elevada ({pendencias})")
        elif pendencias >= 5:
            score -= 8
            penalidades.append(f"fila de pendências moderada ({pendencias})")

    if _claims_conhecido(metrics):
        if claims_val >= 0.02:
            score -= 30
            penalidades.append(f"taxa de reclamação alta ({claims_val * 100:.2f}%)")
        elif claims_val >= 0.01:
            score -= 15
            penalidades.append(f"taxa de reclamação em atenção ({claims_val * 100:.2f}%)")
    elif perfil in ("shopee", "magalu", "amazon"):
        penalidades.append("claims não medido neste canal — score não assume 0% saudável")

    if dias_sem_acesso >= 7:
        score -= 25
        penalidades.append(f"{dias_sem_acesso} dias sem acesso")
    elif dias_sem_acesso >= 3:
        score -= 12
        penalidades.append(f"{dias_sem_acesso} dias sem acesso")

    if perfil == "amazon" and metrics.get("estoque_sync") is False:
        score -= 20
        penalidades.append("estoque Amazon fora do sync Bling — risco de oversell / perder Buy Box")

    return max(0, min(100, score)), penalidades, None


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


def _ajustes_recomendados(metrics: dict, score_atual: int, media_historica: float | None, variacoes: list[dict], nome: str = "") -> list[str]:
    if not metrics.get("configurado", False):
        return ["canal inativo/não configurado — sem alerta Telegram até ativar credenciais"]

    perfil = _perfil(nome)
    acoes = []
    pendencias = int(metrics.get("pendencias", 0) or 0)
    claims_val = 0.0
    try:
        if metrics.get("claims_rate") is not None:
            claims_val = float(metrics.get("claims_rate") or 0)
    except (TypeError, ValueError):
        claims_val = 0.0
    dias_sem_acesso = int(metrics.get("dias_sem_acesso", 0) or 0)

    if dias_sem_acesso >= 2:
        acoes.append("executar keepalive imediato e validar token")
    if perfil == "shopee" and pendencias >= 3:
        acoes.append("priorizar chat Shopee nas próximas 2h — SLA de resposta entra no ranking")
    elif perfil == "amazon" and pendencias >= 15:
        acoes.append("responder mensagens Amazon (pós-venda); ranking segue Buy Box/preço/estoque")
    elif pendencias >= 15:
        acoes.append("priorizar respostas de perguntas/mensagens nas próximas 2h")
    if _claims_conhecido(metrics) and claims_val >= 0.01:
        acoes.append("reduzir promessas nos anúncios e revisar SLAs para conter reclamações")
    if perfil == "amazon":
        acoes.append("Buy Box: conferir preço, estoque e prazo — fila de chat não substitui isso")
        if metrics.get("estoque_sync") is False:
            acoes.append("incluir Amazon no sync de estoque Bling antes de operar anúncio")
    if score_atual < 60:
        acoes.append("reduzir mudanças agressivas de preço por 24h e estabilizar atendimento")

    if media_historica is not None and (media_historica - score_atual) >= 15:
        acoes.append("queda brusca detectada: revisar títulos, preço e estoque imediatamente")

    for ajuste in _ajustes_finos_vendas(variacoes, score_atual):
        acoes.append(ajuste)

    if not acoes:
        acoes.append("manter estratégia atual e seguir monitoramento")
    return list(dict.fromkeys(acoes))


def avaliar_marketplace(nome: str, metrics: dict) -> dict:
    historico = _load_history()
    pontos = historico.get(nome, [])

    score_atual, penalidades, status_forcado = _score_from_metrics(metrics, nome)
    metrics_com_score = {**metrics, "score_atual": score_atual}
    media_historica = None
    if pontos and status_forcado is None:
        media_historica = sum(p.get("score", 0) for p in pontos[-10:]) / min(len(pontos), 10)
    ponto_anterior = pontos[-1] if pontos else None
    variacoes = (
        []
        if status_forcado == "inativo"
        else _detectar_variacoes_relevantes(metrics_com_score, ponto_anterior)
    )

    avaliacao = {
        "marketplace": nome,
        "score": score_atual,
        "status": status_forcado or _classificar(score_atual),
        "penalidades": penalidades,
        "variacoes_relevantes": variacoes,
        "acoes_recomendadas": _ajustes_recomendados(metrics, score_atual, media_historica, variacoes, nome),
        "metrics": metrics,
        "modelo": _perfil(nome),
        "media_historica": round(media_historica, 1) if media_historica is not None else None,
    }

    # Não grava histórico de canal inativo — evita “queda brusca” falsa ao ativar.
    if status_forcado != "inativo":
        pontos.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "score": score_atual,
            "metrics": metrics,
        })
        historico[nome] = pontos[-100:]
        _save_history(historico)

    return avaliacao
