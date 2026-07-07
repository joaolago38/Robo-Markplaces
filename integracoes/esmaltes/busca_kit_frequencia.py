"""
integracoes/esmaltes/busca_kit_frequencia.py
Busca kits de esmaltes Anita/Impala no ML e contabiliza frequência diária por cor.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from core.config import ESMALTES_BUSCA_KIT_TOLERANCIA_ERRO
from integracoes.esmaltes.analise_anita import cores_no_titulo, detectar_marca, extrair_qtd_kit

logger = logging.getLogger("busca_kit_frequencia")


def _termos_busca_item(item: dict[str, Any]) -> list[str]:
    """Termo principal + alternativos do catálogo + fallbacks automáticos."""
    vistos: set[str] = set()
    termos: list[str] = []
    for bruto in [item.get("termo_busca"), *(item.get("termos_alternativos") or [])]:
        t = str(bruto or "").strip()
        chave = t.lower()
        if t and chave not in vistos:
            vistos.add(chave)
            termos.append(t)

    marca = str(item.get("marca") or "").strip().lower()
    qtd = item.get("qtd_esmaltes")
    if marca and qtd:
        for auto in (
            f"kit {qtd} esmaltes {marca} manicure",
            f"esmalte {marca} kit manicure",
        ):
            if auto.lower() not in vistos:
                vistos.add(auto.lower())
                termos.append(auto)
    return termos


def _score_anuncio(item: dict[str, Any], anuncio: dict[str, Any]) -> int:
    titulo = str(anuncio.get("titulo") or "")
    norm = titulo.lower()
    marca = str(item.get("marca") or "").lower()
    score = 0
    if "esmalte" in norm or "kit" in norm:
        score += 1
    if marca and marca in norm:
        score += 3
    qtd = item.get("qtd_esmaltes")
    if qtd:
        qtd_titulo = extrair_qtd_kit(titulo)
        if qtd_titulo == int(qtd):
            score += 2
        elif str(qtd) in norm:
            score += 1
    if cores_no_titulo(titulo, [str(c) for c in (item.get("cores_busca") or [])]):
        score += 1
    return score


def _filtrar_anuncios(
    item: dict[str, Any],
    anuncios: list[dict[str, Any]],
    limite: int,
    *,
    tolerancia_erro: float = ESMALTES_BUSCA_KIT_TOLERANCIA_ERRO,
) -> list[dict[str, Any]]:
    """
    Mantém anúncios relevantes com tolerância de ~10% de imprecisão
    (ex.: kit esmalte sem a marca exata, mas ainda do nicho).
    """
    if not anuncios:
        return []

    limite = max(1, limite)
    tolerancia = max(0.0, min(0.5, tolerancia_erro))
    max_imprecisos = max(1, int(limite * tolerancia))

    pontuados = sorted(
        ((a, _score_anuncio(item, a)) for a in anuncios),
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
            iid = str(an.get("item_id") or an.get("titulo") or "")
            if iid in vistos:
                continue
            vistos.add(iid)
            out.append(an)
            if len(out) >= limite:
                return out
    return out


def buscar_anuncios_item(
    item: dict[str, Any],
    buscar_fn: Callable[..., list[dict[str, Any]]],
    *,
    tolerancia_erro: float = ESMALTES_BUSCA_KIT_TOLERANCIA_ERRO,
) -> tuple[list[dict[str, Any]], str]:
    """
    Tenta termos em cascata até obter resultados. Retorna (anúncios, termo_usado).
    """
    limite = int(item.get("limite_resultados") or 20)
    item_ref = str(item.get("item_id_ml") or item.get("item_id_referencia") or "").strip() or None
    termos = _termos_busca_item(item)
    melhor: list[dict[str, Any]] = []
    termo_usado = str(item.get("termo_busca") or "")

    for termo in termos:
        brutos = buscar_fn(termo, limite=limite, item_id_referencia=item_ref)
        filtrados = _filtrar_anuncios(item, brutos, limite, tolerancia_erro=tolerancia_erro)
        if len(filtrados) > len(melhor):
            melhor = filtrados
            termo_usado = termo
        if filtrados:
            logger.info(
                "Busca kit [%s] termo=%r → %d anúncio(s) (%d bruto)",
                item.get("id"),
                termo,
                len(filtrados),
                len(brutos),
            )
            return filtrados, termo_usado

    return melhor, termo_usado


def _chave_dia(agora: datetime | None = None) -> str:
    dt = agora or datetime.now(timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d")


def _contar_cores_anuncios(anuncios: list[dict[str, Any]], cores_busca: list[str]) -> dict[str, int]:
    contagem: dict[str, int] = {c: 0 for c in cores_busca}
    for an in anuncios:
        titulo = str(an.get("titulo") or "")
        for cor in cores_no_titulo(titulo, cores_busca):
            contagem[cor] = contagem.get(cor, 0) + 1
    return {k: v for k, v in contagem.items() if v > 0}


def _resumir_anuncios(anuncios: list[dict[str, Any]], marca_esperada: str) -> dict[str, Any]:
    marca_norm = marca_esperada.lower()
    da_marca = 0
    kits = 0
    for an in anuncios:
        titulo = str(an.get("titulo") or "")
        if marca_norm in titulo.lower():
            da_marca += 1
        if extrair_qtd_kit(titulo):
            kits += 1
    return {
        "total": len(anuncios),
        "da_marca": da_marca,
        "com_kit_no_titulo": kits,
        "marcas_detectadas": _top_marcas(anuncios),
    }


def _top_marcas(anuncios: list[dict[str, Any]], limite: int = 4) -> list[dict[str, Any]]:
    freq: dict[str, int] = {}
    for an in anuncios:
        m = detectar_marca(str(an.get("titulo") or ""))
        freq[m] = freq.get(m, 0) + 1
    ordenado = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [{"marca": m, "qtd": q} for m, q in ordenado[:limite]]


def executar_busca_item(
    item: dict[str, Any],
    anuncios: list[dict[str, Any]],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Processa resultado de uma busca ML para um item do catálogo."""
    cores_busca = [str(c).strip() for c in (item.get("cores_busca") or []) if str(c).strip()]
    marca = str(item.get("marca") or "").lower()
    resumo = _resumir_anuncios(anuncios, marca)
    cores = _contar_cores_anuncios(anuncios, cores_busca)
    ts = timestamp or datetime.now(timezone.utc).isoformat()

    return {
        "ok": True,
        "item_id": item.get("id"),
        "nome": item.get("nome"),
        "marca": marca,
        "cor_foco": item.get("cor_foco"),
        "termo_busca": item.get("termo_busca"),
        "termo_usado": item.get("termo_usado") or item.get("termo_busca"),
        "timestamp": ts,
        "total_anuncios": resumo["total"],
        "anuncios_da_marca": resumo["da_marca"],
        "kits_no_titulo": resumo["com_kit_no_titulo"],
        "cores_encontradas": cores,
        "top_marcas": resumo["marcas_detectadas"],
    }


def registrar_execucao_diaria(
    historico: dict[str, Any],
    resultado: dict[str, Any],
    *,
    dia: str | None = None,
) -> dict[str, Any]:
    """Incrementa contadores do dia no histórico (mutação in-place + retorno do dia)."""
    chave = dia or _chave_dia()
    dia_obj: dict[str, Any] = historico.setdefault(
        chave,
        {
            "total_buscas": 0,
            "anita": 0,
            "impala": 0,
            "itens": {},
            "execucoes": [],
        },
    )

    marca = str(resultado.get("marca") or "").lower()
    item_id = str(resultado.get("item_id") or "desconhecido")

    dia_obj["total_buscas"] = int(dia_obj.get("total_buscas") or 0) + 1
    if marca == "anita":
        dia_obj["anita"] = int(dia_obj.get("anita") or 0) + 1
    elif marca == "impala":
        dia_obj["impala"] = int(dia_obj.get("impala") or 0) + 1

    itens: dict[str, Any] = dia_obj.setdefault("itens", {})
    reg = itens.setdefault(
        item_id,
        {
            "nome": resultado.get("nome"),
            "marca": marca,
            "cor_foco": resultado.get("cor_foco"),
            "buscas": 0,
            "total_anuncios_acum": 0,
            "cores_encontradas": {},
        },
    )
    reg["buscas"] = int(reg.get("buscas") or 0) + 1
    reg["total_anuncios_acum"] = int(reg.get("total_anuncios_acum") or 0) + int(
        resultado.get("total_anuncios") or 0
    )
    cores_acum: dict[str, int] = reg.setdefault("cores_encontradas", {})
    for cor, qtd in (resultado.get("cores_encontradas") or {}).items():
        cores_acum[cor] = int(cores_acum.get(cor) or 0) + int(qtd)

    execucoes: list[dict[str, Any]] = dia_obj.setdefault("execucoes", [])
    execucoes.append(
        {
            "timestamp": resultado.get("timestamp"),
            "item_id": item_id,
            "marca": marca,
            "cor_foco": resultado.get("cor_foco"),
            "termo": resultado.get("termo_busca"),
            "anuncios": resultado.get("total_anuncios"),
        }
    )
    if len(execucoes) > 100:
        dia_obj["execucoes"] = execucoes[-100:]

    return dia_obj


def consolidar_dia(dia_obj: dict[str, Any]) -> dict[str, Any]:
    """KPIs agregados de um dia."""
    itens = dia_obj.get("itens") or {}
    cores_globais: dict[str, int] = {}
    for reg in itens.values():
        for cor, qtd in (reg.get("cores_encontradas") or {}).items():
            cores_globais[cor] = cores_globais.get(cor, 0) + int(qtd)

    top_cores = sorted(cores_globais.items(), key=lambda x: x[1], reverse=True)[:8]
    return {
        "total_buscas": int(dia_obj.get("total_buscas") or 0),
        "anita": int(dia_obj.get("anita") or 0),
        "impala": int(dia_obj.get("impala") or 0),
        "itens_distintos": len(itens),
        "top_cores": [{"cor": c, "mencoes": q} for c, q in top_cores],
    }
