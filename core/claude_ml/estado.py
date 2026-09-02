"""core/claude_ml/estado.py — carrega estado atual do Mercado Livre (SRP)."""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.claude_ml.numeros import num
from core.config import ROOT

logger = logging.getLogger("claude_ml_estado")

_ORD_NIVEL = {"desconhecido": 0, "ok": 1, "atencao": 2, "critico": 3}


def _snapshot(nome: str) -> dict[str, Any]:
    data = ler_json(ROOT / "logs" / nome, default={})
    return data if isinstance(data, dict) else {}


def nivel_de_score(score: float | None) -> str:
    if score is None:
        return "desconhecido"
    if score >= 75:
        return "ok"
    if score >= 50:
        return "atencao"
    return "critico"


def _subir(atual: str, alvo: str) -> str:
    return alvo if _ORD_NIVEL.get(alvo, 0) > _ORD_NIVEL.get(atual, 0) else atual


def carregar_estado_ml(*, ao_vivo: bool = False) -> dict[str, Any]:
    """Bloco compacto do 'como o ML está' (snapshots; API opcional)."""
    hist = _snapshot("marketplace_algorithm_history.json")
    pontos_ml = hist.get("mercadolivre") if isinstance(hist, dict) else None
    ultimo_algo: dict[str, Any] = {}
    if isinstance(pontos_ml, list) and pontos_ml:
        ultimo = pontos_ml[-1]
        if isinstance(ultimo, dict):
            ultimo_algo = ultimo

    resumo_conta = _snapshot("resumo_conta_ml_ultima.json")
    margem = _snapshot("margem_vendas_ultima.json")
    sem_venda = _snapshot("sem_venda_ml_ultima.json")
    estrategia = _snapshot("relatorio_estrategia_ml_ultima.json")
    manha = _snapshot("relatorio_manha_ml_ultima.json")
    decisao = _snapshot("decisao_dia_esmaltes_ultima.json")
    eco = _snapshot("ecossistema_esmaltes_ultima.json")

    score = ultimo_algo.get("score")
    if score is None:
        score = resumo_conta.get("score") or resumo_conta.get("score_ml")
    score_f = num(score, default=-1)
    score_opt = None if score_f < 0 else score_f
    nivel = nivel_de_score(score_opt)

    alertas: list[str] = []
    metrics = ultimo_algo.get("metrics") if isinstance(ultimo_algo.get("metrics"), dict) else {}
    pendencias = metrics.get("pendencias")
    claims = metrics.get("claims_rate")
    if pendencias is None:
        pendencias = resumo_conta.get("pendencias") or resumo_conta.get("perguntas_pendentes")
    if claims is None:
        rep = resumo_conta.get("reputacao") if isinstance(resumo_conta.get("reputacao"), dict) else {}
        claims = resumo_conta.get("claims_rate") or rep.get("claims_rate")

    if num(pendencias) >= 5:
        alertas.append(f"perguntas/pendências altas ({int(num(pendencias))})")
        nivel = _subir(nivel, "atencao")
    if num(claims) >= 0.02:
        alertas.append(f"claims_rate elevado ({num(claims):.3f})")
    if num(claims) >= 0.05:
        nivel = _subir(nivel, "critico")
    elif num(claims) >= 0.02:
        nivel = _subir(nivel, "atencao")

    saude_vivo: dict[str, Any] | None = None
    if ao_vivo:
        try:
            from integracoes.ml.ml_client import obter_saude_conta

            saude_vivo = obter_saude_conta()
            if isinstance(saude_vivo, dict) and saude_vivo.get("configurado"):
                if num(saude_vivo.get("pendencias")) >= 5:
                    nivel = _subir(nivel, "atencao")
                if num(saude_vivo.get("claims_rate")) >= 0.05:
                    nivel = _subir(nivel, "critico")
                elif num(saude_vivo.get("claims_rate")) >= 0.02:
                    nivel = _subir(nivel, "atencao")
        except Exception as exc:
            logger.debug("estado_ml ao_vivo falhou: %s", exc)

    anuncios: dict[str, Any] = {"total": 0, "publicados": 0, "pendente_mlb": 0, "fonte": "vazio", "itens": []}
    try:
        from core.claude_ml.anuncios import bloco_anuncios_ml

        anuncios = bloco_anuncios_ml(
            resumo_conta=resumo_conta if isinstance(resumo_conta, dict) else None,
            sem_venda=sem_venda if isinstance(sem_venda, dict) else None,
            ao_vivo=ao_vivo,
        )
        if int(anuncios.get("pendente_mlb") or 0) > 0:
            alertas.append(f"{int(anuncios['pendente_mlb'])} anúncio(s) sem MLB válido")
            nivel = _subir(nivel, "atencao")
    except Exception as exc:
        logger.debug("anuncios no estado_ml: %s", exc)

    return {
        "marketplace": "mercadolivre",
        "nivel": nivel,
        "score_algoritmo": score_opt,
        "status_algoritmo": ultimo_algo.get("status") or nivel,
        "metrics_algoritmo": {
            "pendencias": pendencias,
            "claims_rate": claims,
            "dias_sem_acesso": metrics.get("dias_sem_acesso"),
        },
        "saude_ao_vivo": saude_vivo,
        "alertas": alertas[:6],
        "sinais_recentes": {
            "margem_vendas": {
                "margem_media_pct": (
                    margem.get("margem_media_pct")
                    or margem.get("margem_media")
                    or (margem.get("analise") or {}).get("margem_media_pct")
                ),
                "vendas": (
                    margem.get("total_vendas")
                    or margem.get("vendas")
                    or (margem.get("analise") or {}).get("total_itens")
                ),
                "alerta": margem.get("alerta") or margem.get("status"),
            },
            "sem_venda": {
                "itens": sem_venda.get("total")
                or sem_venda.get("quantidade")
                or sem_venda.get("itens_sem_venda"),
                "alerta": sem_venda.get("alerta"),
            },
            "decisao_esmaltes_score": decisao.get("score") or decisao.get("score_dia"),
            "ecossistema_score": eco.get("score_ecossistema") or eco.get("score"),
            "estrategia_resumo": str(
                estrategia.get("resumo") or estrategia.get("titulo") or ""
            )[:160]
            or None,
            "manha_tem_dados": bool(manha),
        },
        "fonte": "snapshots_logs" + ("+api" if saude_vivo else ""),
        "anuncios": anuncios,
    }
