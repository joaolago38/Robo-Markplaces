"""
integracoes/filamentos/custos_masterprint_petg.py
Custos PETG Masterprint a partir da tabela MA-MASTER Revenda 06 (PDF → JSON).

Casa anúncio ML (cor/peso/variante no título) com SKU da tabela e calcula
margem líquida após taxa do marketplace.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache
from typing import Any

from core.atomic_io import ler_json
from core.config import (
    FILAMENTOS_SOURCING_TAXA_ML_PCT,
    MASTERPRINT_PETG_CUSTOS,
    ROOT,
)
from integracoes.filamentos.analise_filamentos_ml import detectar_peso_kg
from integracoes.importacao.custo_landed import calcular_margem_revenda

logger = logging.getLogger("custos_masterprint_petg")

_RE_ESPACO = re.compile(r"\s+")

# (tag, aliases no título / cor_raw)
_VARIANTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("carbono", ("fibra de carbono", "carbono", "carbon fiber")),
    ("fosco", ("fosco", "matte")),
    ("fosforescente", ("fosforescente", "glow", "brilha no escuro")),
    ("fluorescente", ("fluorescente",)),
    ("pcv_indoor", ("pcv indoor", "indoor")),
    ("pcv_outdoor", ("pcv outdoor", "outdoor")),
    ("etiqueta_neutra", ("etiqueta neutra", "neutra")),
)


def _norm(texto: str) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _RE_ESPACO.sub(" ", s.lower()).strip()


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def carregar_tabela_custos(caminho: str | None = None) -> dict[str, Any]:
    path = ROOT / (caminho or MASTERPRINT_PETG_CUSTOS)
    data = ler_json(path, default={})
    # Fallback: BOM / backend vazio — lê o arquivo direto
    if not isinstance(data, dict) or not data.get("itens"):
        try:
            import json

            raw = path.read_text(encoding="utf-8-sig")
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("itens"):
                data = parsed
        except Exception as exc:
            logger.warning("Falha ao ler custos Masterprint em %s: %s", path, exc)
            data = {}
    if not isinstance(data, dict):
        logger.warning("Catálogo custos Masterprint inválido: %s", path)
        return {"itens": [], "custo_padrao_1kg_brl": 0.0}
    itens = [i for i in (data.get("itens") or []) if isinstance(i, dict) and i.get("ativo")]
    return {
        "fornecedor": data.get("fornecedor"),
        "tabela": data.get("tabela"),
        "valida_a_partir_de": data.get("valida_a_partir_de"),
        "custo_padrao_1kg_brl": _f(data.get("custo_padrao_1kg_brl"), 45.96),
        "itens": itens,
        "fonte": str(path),
    }


def limpar_cache_custos() -> None:
    carregar_tabela_custos.cache_clear()


def _tags_variante(texto_n: str) -> frozenset[str]:
    tags: set[str] = set()
    for tag, aliases in _VARIANTES:
        if any(a in texto_n for a in aliases):
            tags.add(tag)
    return frozenset(tags)


def _score_item(titulo_n: str, tags_titulo: frozenset[str], item: dict[str, Any]) -> int:
    cor_n = _norm(str(item.get("cor_raw") or item.get("cor") or ""))
    if not cor_n:
        return 0

    partes = [p for p in cor_n.split() if p not in ("de", "da", "do")]
    # núcleo de cor: última palavra costuma ser a cor (PRETO, BRANCO…)
    nucleo = partes[-1] if partes else ""
    if nucleo and nucleo not in titulo_n:
        # cores compostas tipo "cool grey" / "green olive"
        if not all(p in titulo_n for p in partes):
            return 0

    score = 10 + len(cor_n)
    if all(p in titulo_n for p in partes):
        score += 25

    tags_item = _tags_variante(cor_n)
    # Bônus se variantes batem; penaliza mismatch
    if tags_item == tags_titulo:
        score += 50
    else:
        comuns = tags_item & tags_titulo
        score += 20 * len(comuns)
        # SKU com variante que o título não tem (ex.: fosco no SKU, liso no título)
        extras_item = tags_item - tags_titulo
        extras_titulo = tags_titulo - tags_item
        score -= 35 * len(extras_item)
        score -= 20 * len(extras_titulo)

    return score


def casar_custo_anuncio(
    titulo: str,
    *,
    peso_kg: float | None = None,
    tabela: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Retorna o melhor SKU da tabela para o título, ou custo padrão 1kg."""
    tab = tabela or carregar_tabela_custos()
    itens: list[dict[str, Any]] = list(tab.get("itens") or [])
    if not itens:
        return None

    titulo_n = _norm(titulo)
    peso = peso_kg if peso_kg and peso_kg > 0 else detectar_peso_kg(titulo)
    if peso is None or peso <= 0:
        peso = 1.0

    tags_titulo = _tags_variante(titulo_n)
    candidatos = [i for i in itens if abs(_f(i.get("peso_kg"), 1.0) - float(peso)) < 0.05]
    if not candidatos:
        candidatos = [i for i in itens if abs(_f(i.get("peso_kg"), 1.0) - 1.0) < 0.05]

    melhor: dict[str, Any] | None = None
    melhor_score = 0
    for item in candidatos:
        sc = _score_item(titulo_n, tags_titulo, item)
        if sc > melhor_score:
            melhor_score = sc
            melhor = item

    padrao = _f(tab.get("custo_padrao_1kg_brl"), 45.96)
    meta = {
        "tabela": tab.get("tabela"),
        "valida_a_partir_de": tab.get("valida_a_partir_de"),
    }

    if melhor is None or melhor_score < 10:
        if abs(float(peso) - 1.0) > 0.05:
            return {
                "sku": None,
                "cor": "Padrao",
                "peso_kg": float(peso),
                "custo_unitario_brl": round(padrao * float(peso), 2),
                "match": "custo_padrao_escalado",
                **meta,
            }
        return {
            "sku": None,
            "cor": "Padrao",
            "peso_kg": 1.0,
            "custo_unitario_brl": padrao,
            "match": "custo_padrao_1kg",
            **meta,
        }

    return {
        "sku": melhor.get("sku"),
        "cor": melhor.get("cor"),
        "peso_kg": _f(melhor.get("peso_kg"), 1.0),
        "custo_unitario_brl": _f(melhor.get("custo_unitario_brl")),
        "match": "sku_tabela",
        "score": melhor_score,
        **meta,
    }


def enriquecer_com_margem(
    produto: dict[str, Any],
    *,
    taxa_ml_pct: float | None = None,
    tabela: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Anexa custo da tabela + margem líquida (após taxa ML)."""
    out = dict(produto)
    taxa = FILAMENTOS_SOURCING_TAXA_ML_PCT if taxa_ml_pct is None else float(taxa_ml_pct)
    peso = out.get("peso_kg")
    try:
        peso_f = float(peso) if peso is not None else None
    except (TypeError, ValueError):
        peso_f = None

    custo_info = casar_custo_anuncio(
        str(out.get("titulo") or ""),
        peso_kg=peso_f,
        tabela=tabela,
    )
    if not custo_info:
        out["custo_unitario_brl"] = None
        out["margem_brl"] = None
        out["margem_pct"] = None
        out["lucro_proxy"] = None
        out["custo_match"] = None
        return out

    custo = _f(custo_info.get("custo_unitario_brl"))
    margem = calcular_margem_revenda(
        _f(out.get("preco")),
        custo,
        taxa_marketplace_pct=taxa,
        margem_minima_pct=0.0,
        margem_minima_reais=0.0,
    )
    vendidos = int(out.get("quantidade_vendida") or 0)
    margem_brl = float(margem.get("margem_brl") or 0) if margem.get("ok") else 0.0
    out["custo_unitario_brl"] = custo
    out["custo_sku"] = custo_info.get("sku")
    out["custo_cor"] = custo_info.get("cor")
    out["custo_match"] = custo_info.get("match")
    out["taxa_ml_pct"] = taxa
    out["liquido_apos_taxa_brl"] = margem.get("liquido_apos_taxa_brl")
    out["margem_brl"] = margem.get("margem_brl")
    out["margem_pct"] = margem.get("margem_pct")
    out["lucro_proxy"] = round(margem_brl * max(0, vendidos), 2)
    return out


def top_por_margem(produtos: list[dict[str, Any]], top_n: int = 10) -> list[dict[str, Any]]:
    """Ranking por lucro proxy (margem unitária × vendas), depois margem %."""
    ordenados = sorted(
        produtos,
        key=lambda p: (
            float(p.get("lucro_proxy") or 0),
            float(p.get("margem_brl") or 0),
            float(p.get("margem_pct") or 0),
        ),
        reverse=True,
    )
    out = []
    for i, p in enumerate(ordenados[:top_n], 1):
        row = dict(p)
        row["rank"] = i
        out.append(row)
    return out
