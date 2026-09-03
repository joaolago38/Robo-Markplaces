"""
integracoes/ml/agrupador_reclamacoes.py
Agrupa reclamações por palavra-chave (não é NLP / análise semântica).
Revisar os trechos com olho humano antes de usar em anúncio ou FAQ.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT
from core.datadog_metrics import gauge

logger = logging.getLogger("agrupador_reclamacoes")

CATALOGO_PATH = ROOT / "catalogo" / "palavras_chave_reclamacao.json"


def _normalizar(texto: str) -> str:
    bruto = str(texto or "").lower()
    nfkd = unicodedata.normalize("NFKD", bruto)
    sem_acento = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return " ".join(sem_acento.split())


def _carregar_padroes() -> list[dict[str, Any]]:
    data = ler_json(CATALOGO_PATH, default={})
    if not isinstance(data, dict):
        return []
    rows = data.get("padroes") or []
    return [p for p in rows if isinstance(p, dict) and p.get("id")]


def _textos_reclamacao(
    avaliacoes: list[dict[str, Any]],
    perguntas: list[dict[str, Any]],
) -> list[str]:
    originais: list[str] = []
    for item in avaliacoes or []:
        if not isinstance(item, dict):
            continue
        nota = item.get("nota_estrelas")
        if nota is None:
            nota = item.get("estrelas")
        try:
            n = int(nota) if nota is not None else None
        except (TypeError, ValueError):
            n = None
        if n is not None and n > 3:
            continue
        t = str(item.get("texto") or item.get("content") or "").strip()
        if t:
            originais.append(t)
    for item in perguntas or []:
        if isinstance(item, dict):
            t = str(item.get("texto") or item.get("text") or "").strip()
        else:
            t = str(item or "").strip()
        if t:
            originais.append(t)
    return originais


def agrupar_padroes_reclamacao(
    avaliacoes: list[dict[str, Any]],
    perguntas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Junta avaliações com nota <= 3 e o texto das perguntas.
    Conta substrings de catalogo/palavras_chave_reclamacao.json.
    Retorna [{padrao, frequencia, exemplos}] com no máximo 3 exemplos.
    """
    originais = _textos_reclamacao(avaliacoes, perguntas)
    if not originais:
        return []
    try:
        saida: list[dict[str, Any]] = []
        for padrao in _carregar_padroes():
            termos = [_normalizar(t) for t in (padrao.get("termos") or []) if str(t).strip()]
            exemplos: list[str] = []
            freq = 0
            for orig in originais:
                if any(term and term in _normalizar(orig) for term in termos):
                    freq += 1
                    if len(exemplos) < 3:
                        exemplos.append(orig[:280])
            if freq <= 0:
                continue
            saida.append(
                {
                    "padrao": str(padrao.get("id") or ""),
                    "frequencia": freq,
                    "exemplos": exemplos,
                }
            )
        saida.sort(key=lambda r: -int(r.get("frequencia") or 0))
        return saida
    except Exception as exc:
        logger.warning("agrupar_padroes_reclamacao: %s", exc)
        return []


def emitir_metricas_reclamacao(
    padroes: list[dict[str, Any]],
    tags: list[str] | None = None,
) -> None:
    """Gauges robo.reclamacao.* por padrão fechado do catálogo (não é NLP)."""
    base = list(tags or [])
    rows = [p for p in (padroes or []) if isinstance(p, dict)]
    total = 0
    for row in rows:
        try:
            total += int(row.get("frequencia") or 0)
        except (TypeError, ValueError):
            continue
    gauge("reclamacao.total", float(total), tags=base)
    for row in rows[:12]:
        pid = str(row.get("padrao") or "").strip()
        if not pid:
            continue
        try:
            freq = float(int(row.get("frequencia") or 0))
        except (TypeError, ValueError):
            continue
        gauge("reclamacao.frequencia", freq, tags=[*base, f"padrao:{pid[:40]}"])
