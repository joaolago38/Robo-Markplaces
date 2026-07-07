"""
integracoes/esmaltes/busca_removedores.py
Busca removedores de unha no ML com termos em cascata e filtro com tolerância.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from core.config import REMOVEDORES_UNHA_TOLERANCIA_ERRO
from integracoes.esmaltes.analise_acetona_cruzeiro import eh_listing_acetona
from integracoes.esmaltes.analise_removedores import classificar_removedor, detectar_fabricante

logger = logging.getLogger("busca_removedores")

_FALLBACKS_POR_ID: dict[str, tuple[str, ...]] = {
    "removedor-geral": ("acetona manicure", "removedor esmalte", "removedor unha"),
    "acetona-geral": ("acetona manicure", "acetona profissional", "removedor esmalte"),
    "cruzeiro": ("acetona cruzeiro", "removedor cruzeiro", "acetona cruzeiro 100ml"),
    "impala": ("acetona impala", "removedor impala"),
    "risque": ("acetona risque", "removedor risque"),
    "colorama": ("acetona colorama", "removedor colorama"),
    "nati": ("acetona nati", "removedor nati"),
    "acetona-100": ("acetona 100ml", "acetona manicure 100ml"),
    "acetona-500": ("acetona 500ml", "acetona profissional 500ml"),
    "sem-acetona": ("removedor sem acetona", "diluidor esmalte"),
}


def _termos_busca_segmento(segmento: dict[str, Any]) -> list[str]:
    vistos: set[str] = set()
    termos: list[str] = []

    def _add(bruto: Any) -> None:
        t = str(bruto or "").strip()
        chave = t.lower()
        if t and chave not in vistos:
            vistos.add(chave)
            termos.append(t)

    for bruto in [segmento.get("termo_busca"), *(segmento.get("termos_alternativos") or [])]:
        _add(bruto)
    for bruto in segmento.get("termos_ia") or []:
        _add(bruto)

    seg_id = str(segmento.get("id") or "")
    for auto in _FALLBACKS_POR_ID.get(seg_id, ()):
        _add(auto)

    marca = str(segmento.get("marca") or seg_id or "").strip().lower()
    if marca and marca not in ("removedor-geral", "acetona-geral", "sem-acetona"):
        for auto in (f"acetona {marca}", f"removedor {marca}"):
            _add(auto)

    return termos


def _score_removedor(segmento: dict[str, Any], anuncio: dict[str, Any]) -> int:
    titulo = str(anuncio.get("titulo") or "")
    norm = titulo.lower()
    score = 0
    if eh_listing_acetona(titulo):
        score += 2
    seg_id = str(segmento.get("id") or "").lower()
    if seg_id and seg_id not in ("removedor-geral", "acetona-geral", "acetona-100", "acetona-500", "sem-acetona"):
        if seg_id in norm or seg_id.replace("-", " ") in norm:
            score += 3
    fab = detectar_fabricante(titulo).lower()
    if fab not in ("indefinida", "genérico/outros") and fab in norm:
        score += 2
    if "ml" in norm or "100ml" in norm or "500ml" in norm:
        score += 1
    return score


def _filtrar_relevancia(
    segmento: dict[str, Any],
    anuncios: list[dict[str, Any]],
    limite: int,
    *,
    tolerancia_erro: float = REMOVEDORES_UNHA_TOLERANCIA_ERRO,
) -> list[dict[str, Any]]:
    if not anuncios:
        return []

    limite = max(1, limite)
    max_imprecisos = max(1, int(limite * max(0.0, min(0.5, tolerancia_erro))))

    pontuados = sorted(
        ((a, _score_removedor(segmento, a)) for a in anuncios),
        key=lambda x: x[1],
        reverse=True,
    )
    relevantes = [(a, s) for a, s in pontuados if s > 0]
    if not relevantes:
        return anuncios[:limite]

    precisos = [a for a, s in relevantes if s >= 3]
    imprecisos = [a for a, s in relevantes if s < 3]

    out: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for lista in (precisos, imprecisos[:max_imprecisos]):
        for an in lista:
            chave = str(an.get("item_id") or an.get("titulo") or "")
            if chave in vistos:
                continue
            vistos.add(chave)
            out.append(an)
            if len(out) >= limite:
                return out
    return out


def buscar_removedores_segmento(
    segmento: dict[str, Any],
    buscar_fn: Callable[..., list[dict[str, Any]]],
    *,
    tolerancia_erro: float = REMOVEDORES_UNHA_TOLERANCIA_ERRO,
) -> tuple[list[dict[str, Any]], str, int]:
    """
    Tenta termos em cascata. Retorna (produtos classificados, termo_usado, maior total bruto).
    """
    limite = int(segmento.get("limite_resultados") or 25)
    melhor: list[dict[str, Any]] = []
    termo_usado = str(segmento.get("termo_busca") or "")
    maior_bruto = 0

    for termo in _termos_busca_segmento(segmento):
        brutos = buscar_fn(termo, limite=limite)
        maior_bruto = max(maior_bruto, len(brutos))
        candidatos = [
            classificar_removedor(a)
            for a in brutos
            if eh_listing_acetona(str(a.get("titulo") or ""))
        ]
        filtrados = _filtrar_relevancia(segmento, candidatos, limite, tolerancia_erro=tolerancia_erro)
        if len(filtrados) > len(melhor):
            melhor = filtrados
            termo_usado = termo
        if filtrados:
            logger.info(
                "Busca removedores [%s] termo=%r → %d produto(s) (%d bruto)",
                segmento.get("id"),
                termo,
                len(filtrados),
                len(brutos),
            )
            return filtrados, termo_usado, len(brutos)

    return melhor, termo_usado, maior_bruto
