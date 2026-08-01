"""
core/algoritmo_eventos.py
Eventos tipados a partir da saúde do algoritmo ML → atuadores.

Tipos:
  priorizar_chat      — chat ML deve esvaziar pendências
  congelar_repricing  — não aplicar preço por TTL
  revisar_listing     — otimizador deve priorizar
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ALGORITMO_EVENTOS_ATIVO, ROOT

logger = logging.getLogger("algoritmo_eventos")

EVENTOS_PATH = ROOT / "logs" / "algoritmo_eventos_ativos.json"

TIPOS = frozenset({"priorizar_chat", "congelar_repricing", "revisar_listing"})


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(valor: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def emitir_de_avaliacao(avaliacoes: dict[str, Any]) -> list[dict[str, Any]]:
    """Gera eventos a partir do mapa marketplace → avaliação."""
    if not ALGORITMO_EVENTOS_ATIVO:
        return []
    agora = _agora()
    novos: list[dict[str, Any]] = []
    for nome, av in (avaliacoes or {}).items():
        if not isinstance(av, dict):
            continue
        status = str(av.get("status") or "")
        score = int(av.get("score") or 0)
        metrics = av.get("metrics") or {}
        pendencias = int(metrics.get("pendencias") or 0)
        claims = float(metrics.get("claims_rate") or 0)
        variacoes = av.get("variacoes_relevantes") or []

        if pendencias >= 5 or status in ("atencao", "critico"):
            novos.append(
                {
                    "tipo": "priorizar_chat",
                    "marketplace": nome,
                    "motivo": f"pendencias={pendencias} status={status} score={score}",
                    "criado_em": agora.isoformat(),
                    "expira_em": (agora + timedelta(hours=6)).isoformat(),
                    "prioridade": 1 if pendencias >= 15 or status == "critico" else 2,
                }
            )
        if score < 60 or claims >= 0.01 or status == "critico":
            novos.append(
                {
                    "tipo": "congelar_repricing",
                    "marketplace": nome,
                    "motivo": f"score={score} claims={claims:.4f} status={status}",
                    "criado_em": agora.isoformat(),
                    "expira_em": (agora + timedelta(hours=24)).isoformat(),
                    "prioridade": 1,
                }
            )
        queda = any(
            isinstance(v, dict)
            and v.get("metrica") == "score"
            and float(v.get("variacao_pct") or 0) <= -5
            for v in variacoes
        )
        if queda or status == "critico":
            novos.append(
                {
                    "tipo": "revisar_listing",
                    "marketplace": nome,
                    "motivo": f"queda_score_ou_critico status={status}",
                    "criado_em": agora.isoformat(),
                    "expira_em": (agora + timedelta(hours=48)).isoformat(),
                    "prioridade": 2,
                }
            )
    return novos


def _ativos_validos(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agora = _agora()
    out: list[dict[str, Any]] = []
    vistos: set[tuple[str, str]] = set()
    for ev in sorted(eventos, key=lambda e: int(e.get("prioridade") or 9)):
        if not isinstance(ev, dict):
            continue
        tipo = str(ev.get("tipo") or "")
        mp = str(ev.get("marketplace") or "")
        if tipo not in TIPOS or not mp:
            continue
        exp = _parse_iso(ev.get("expira_em"))
        if exp and exp < agora:
            continue
        key = (tipo, mp)
        if key in vistos:
            continue
        vistos.add(key)
        out.append(ev)
    return out


def persistir_eventos(novos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    data = ler_json(EVENTOS_PATH, default={"eventos": []})
    if not isinstance(data, dict):
        data = {"eventos": []}
    existentes = list(data.get("eventos") or [])
    merged = _ativos_validos(existentes + list(novos or []))
    escrever_json_atomico(
        EVENTOS_PATH,
        {
            "timestamp": _agora().isoformat(),
            "eventos": merged,
        },
    )
    return merged


def listar_ativos(*, marketplace: str | None = None, tipo: str | None = None) -> list[dict[str, Any]]:
    data = ler_json(EVENTOS_PATH, default={"eventos": []})
    eventos = _ativos_validos(list((data or {}).get("eventos") or []))
    if marketplace:
        mp = marketplace.strip().lower()
        eventos = [e for e in eventos if str(e.get("marketplace") or "").lower() == mp]
    if tipo:
        eventos = [e for e in eventos if e.get("tipo") == tipo]
    return eventos


def tem_evento(tipo: str, marketplace: str = "mercadolivre") -> bool:
    return bool(listar_ativos(marketplace=marketplace, tipo=tipo))


def deve_congelar_repricing(marketplace: str = "mercadolivre") -> tuple[bool, str]:
    for ev in listar_ativos(marketplace=marketplace, tipo="congelar_repricing"):
        return True, str(ev.get("motivo") or "congelar_repricing")
    return False, ""


def deve_priorizar_chat(marketplace: str = "mercadolivre") -> tuple[bool, str]:
    for ev in listar_ativos(marketplace=marketplace, tipo="priorizar_chat"):
        return True, str(ev.get("motivo") or "priorizar_chat")
    return False, ""
