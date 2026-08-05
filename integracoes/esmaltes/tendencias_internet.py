"""
integracoes/esmaltes/tendencias_internet.py
Coleta sinais de tendência de esmaltes na web aberta (Brave → DDG).
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from core.brave_search import buscar_web as brave_buscar_web
from core.ddg_lite import buscar as ddg_buscar
from integracoes.esmaltes.analise_anita import _normalizar
from integracoes.esmaltes.analise_mercado import extrair_cores_titulo

logger = logging.getLogger("tendencias_internet")


_TERMOS_TENDENCIA: tuple[str, ...] = (
    "tendencia",
    "tendência",
    "viral",
    "moda",
    "lancamento",
    "lançamento",
    "chrome",
    "holografico",
    "holográfico",
    "jelly",
    "glazed",
    "cateye",
    "cat eye",
    "aura",
    "matte",
    "efeito",
    "nail art",
    "unha decorada",
    "francesinha",
    "french",
    "inverno",
    "verao",
    "verão",
    "festa",
    "profissional",
    "salao",
    "salão",
    "atacado",
)


def _buscar_brave(termo: str, limite: int) -> list[dict[str, str]]:
    brutos = brave_buscar_web(termo, limite=limite, contexto="esmaltes_tendencias")
    out: list[dict[str, str]] = []
    for row in brutos:
        url = str(row.get("url") or "").strip()
        titulo = str(row.get("titulo") or "").strip()
        if url and titulo:
            out.append(
                {
                    "url": url,
                    "titulo": titulo,
                    "snippet": str(row.get("snippet") or ""),
                    "fonte": "brave",
                }
            )
    return out


def _buscar_ddg(termo: str, limite: int) -> list[dict[str, str]]:
    try:
        brutos = ddg_buscar(termo, max_resultados=max(limite * 2, 10), contexto="esmaltes_tendencias")
    except Exception:
        return []
    out: list[dict[str, str]] = []
    for hit in brutos:
        url = str(hit.get("url") or hit.get("link") or "").strip()
        titulo = str(hit.get("titulo") or hit.get("title") or "").strip()
        if url and titulo:
            out.append(
                {
                    "url": url,
                    "titulo": titulo,
                    "snippet": str(hit.get("snippet") or ""),
                    "fonte": "ddg",
                }
            )
    return out


def buscar_web(termo: str, *, limite: int = 15) -> list[dict[str, str]]:
    """Busca na web aberta. Brave primeiro, DDG como fallback."""
    termo = (termo or "").strip()
    if not termo:
        return []

    limite = max(1, min(25, limite))
    vistos: set[str] = set()
    encontrados: list[dict[str, str]] = []

    for fonte_fn in (_buscar_brave, _buscar_ddg):
        hits = fonte_fn(termo, limite)
        for hit in hits:
            url = hit.get("url") or ""
            if not url or url in vistos:
                continue
            vistos.add(url)
            encontrados.append(hit)
            if len(encontrados) >= limite:
                break
        if encontrados:
            logger.info("Web tendências termo=%r → %d hit(s) via %s", termo[:50], len(encontrados), hits[0].get("fonte") if hits else "?")
            return encontrados

    return encontrados


def extrair_sinais_web(hits: list[dict[str, str]]) -> dict[str, Any]:
    """Extrai cores e termos de tendência mencionados na web."""
    cores: Counter[str] = Counter()
    termos: Counter[str] = Counter()
    dominios: Counter[str] = Counter()

    for hit in hits:
        texto = f"{hit.get('titulo', '')} {hit.get('snippet', '')}"
        norm = _normalizar(texto)
        for cor in extrair_cores_titulo(texto):
            cores[cor] += 1
        for termo in _TERMOS_TENDENCIA:
            if termo in norm:
                termos[termo] += 1
        url = str(hit.get("url") or "")
        if "://" in url:
            dom = url.split("/")[2].lower().replace("www.", "")
            if dom:
                dominios[dom] += 1

    return {
        "total_hits": len(hits),
        "cores": [{"cor": c, "mencoes": n} for c, n in cores.most_common(12)],
        "termos": [{"termo": t, "mencoes": n} for t, n in termos.most_common(12)],
        "fontes": [{"dominio": d, "mencoes": n} for d, n in dominios.most_common(8)],
        "hits": hits[:10],
    }


def coletar_segmento_web(segmento: dict[str, Any]) -> dict[str, Any]:
    """Varre todos os termos_web do segmento e agrega sinais."""
    limite = int(segmento.get("limite_resultados") or 15)
    por_termo = max(5, limite // 2)
    todos_hits: list[dict[str, str]] = []
    vistos: set[str] = set()
    termos_ok: list[str] = []

    for bruto in segmento.get("termos_web") or []:
        termo = str(bruto or "").strip()
        if not termo:
            continue
        hits = buscar_web(termo, limite=por_termo)
        if hits:
            termos_ok.append(termo)
        for hit in hits:
            url = hit.get("url") or ""
            if url and url not in vistos:
                vistos.add(url)
                todos_hits.append(hit)

    sinais = extrair_sinais_web(todos_hits)
    sinais["termos_varridos"] = termos_ok
    return sinais
