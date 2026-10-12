"""
integracoes/escritorio/custos_masterprint_escritorio.py
Custos Masterprint: pincéis recarregáveis (permanente / quadro branco) e apagadores.
Tabela MA-MASTER Revenda 06.
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
    MASTERPRINT_ESCRITORIO_CUSTOS,
    ROOT,
)
from integracoes.importacao.custo_landed import calcular_margem_revenda

logger = logging.getLogger("custos_masterprint_escritorio")

_RE_ESPACO = re.compile(r"\s+")
_RE_CX = re.compile(r"(?:caixa|kit|pack)\s*(?:com\s*)?(\d+)|(\d+)\s*(?:unidades|und|un\b|pcs)", re.I)


def _norm(texto: str) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _RE_ESPACO.sub(" ", s.lower()).strip()


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def detectar_tipo(titulo: str) -> str | None:
    n = _norm(titulo)
    if "apagador" in n:
        return "apagador"
    if "quadro branco" in n or "whiteboard" in n:
        return "pincel_quadro_branco"
    if "permanente" in n or "marcador permanente" in n:
        return "pincel_permanente"
    if "pincel" in n or "marcador" in n:
        # genérico — assume permanente se não for quadro
        if "quadro" in n:
            return "pincel_quadro_branco"
        return "pincel_permanente"
    return None


def detectar_cor(titulo: str) -> str | None:
    n = _norm(titulo)
    for nome in ("vermelho", "azul", "preto", "verde", "branca", "branco"):
        if nome in n:
            return nome.title() if nome != "branca" else "Branca"
    return None


def detectar_qtd_embalagem(titulo: str) -> int | None:
    m = _RE_CX.search(titulo or "")
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    try:
        q = int(raw)
    except (TypeError, ValueError):
        return None
    return q if q > 0 else None


@lru_cache(maxsize=1)
def carregar_tabela_custos(caminho: str | None = None) -> dict[str, Any]:
    path = ROOT / (caminho or MASTERPRINT_ESCRITORIO_CUSTOS)
    data = ler_json(path, default={})
    if not isinstance(data, dict) or not data.get("itens"):
        try:
            import json

            parsed = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(parsed, dict) and parsed.get("itens"):
                data = parsed
        except Exception as exc:
            logger.warning("Falha ao ler custos escritório Masterprint: %s", exc)
            data = {}
    if not isinstance(data, dict):
        return {"itens": [], "custos_referencia": {}}
    itens = [i for i in (data.get("itens") or []) if isinstance(i, dict) and i.get("ativo")]
    return {
        "fornecedor": data.get("fornecedor"),
        "tabela": data.get("tabela"),
        "valida_a_partir_de": data.get("valida_a_partir_de"),
        "custos_referencia": data.get("custos_referencia") or {},
        "itens": itens,
        "itens_foco": list(data.get("itens_foco") or []),
        "fonte": str(path),
    }


def limpar_cache_custos() -> None:
    carregar_tabela_custos.cache_clear()


def _itens_foco(tabela: dict[str, Any]) -> list[dict[str, Any]]:
    foco = set(str(x) for x in (tabela.get("itens_foco") or []))
    itens = list(tabela.get("itens") or [])
    if not foco:
        return [
            i
            for i in itens
            if i.get("tipo") == "apagador" or i.get("recarregavel") is True
        ]
    return [i for i in itens if str(i.get("sku")) in foco]


def casar_custo_anuncio(
    titulo: str,
    *,
    tipo: str | None = None,
    tabela: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    tab = tabela or carregar_tabela_custos()
    candidatos = _itens_foco(tab)
    if not candidatos:
        return None

    tipo_t = tipo or detectar_tipo(titulo)
    if not tipo_t:
        return None

    pool = [i for i in candidatos if i.get("tipo") == tipo_t]
    if not pool:
        return None

    cor = detectar_cor(titulo)
    qtd = detectar_qtd_embalagem(titulo)
    titulo_n = _norm(titulo)

    melhor = None
    melhor_score = -10_000
    for item in pool:
        score = 10
        cor_i = str(item.get("cor") or "")
        if cor and cor_i:
            if _norm(cor_i) == _norm(cor):
                score += 40
            else:
                score -= 15
        unids = int(item.get("unidades_por_embalagem") or 1)
        if qtd:
            if qtd == unids:
                score += 50
            elif abs(qtd - unids) <= 2:
                score += 10
            else:
                score -= 20
        else:
            # sem qtd no título: prefere embalagem padrão da tabela
            if unids >= 12 and tipo_t.startswith("pincel"):
                score += 5
            if unids == 1 and tipo_t == "apagador":
                score += 5
        if item.get("codigo_mp") and _norm(str(item["codigo_mp"])) in titulo_n:
            score += 60
        if score > melhor_score:
            melhor_score = score
            melhor = item

    if melhor is None:
        return None

    unids = int(melhor.get("unidades_por_embalagem") or 1)
    custo_emb = _f(melhor.get("custo_embalagem_brl") or melhor.get("custo_unitario_brl"))
    custo_un = _f(melhor.get("custo_unitario_brl"), custo_emb)

    # Se anúncio parece unidade avulsa e tabela é caixa 12 → usa custo por unidade
    vende_caixa = bool(qtd and qtd >= 6) or ("caixa" in titulo_n and (qtd or 12) >= 6)
    if tipo_t.startswith("pincel") and not vende_caixa and unids > 1:
        custo = custo_un
        modo = "unidade_avulsa"
        qtd_custo = 1
    else:
        custo = custo_emb
        modo = "embalagem"
        qtd_custo = unids

    return {
        "sku": melhor.get("sku"),
        "codigo_mp": melhor.get("codigo_mp"),
        "tipo": melhor.get("tipo"),
        "cor": melhor.get("cor"),
        "custo_unitario_brl": round(custo, 4),
        "custo_embalagem_brl": custo_emb,
        "unidades_por_embalagem": qtd_custo,
        "modo_custo": modo,
        "match": "sku_tabela",
        "score": melhor_score,
        "tabela": tab.get("tabela"),
        "valida_a_partir_de": tab.get("valida_a_partir_de"),
    }


def enriquecer_com_margem(
    produto: dict[str, Any],
    *,
    taxa_ml_pct: float | None = None,
    tabela: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(produto)
    taxa = FILAMENTOS_SOURCING_TAXA_ML_PCT if taxa_ml_pct is None else float(taxa_ml_pct)
    custo_info = casar_custo_anuncio(
        str(out.get("titulo") or ""),
        tipo=out.get("tipo"),
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
    out["custo_codigo_mp"] = custo_info.get("codigo_mp")
    out["custo_cor"] = custo_info.get("cor")
    out["custo_match"] = custo_info.get("match")
    out["modo_custo"] = custo_info.get("modo_custo")
    out["taxa_ml_pct"] = taxa
    out["liquido_apos_taxa_brl"] = margem.get("liquido_apos_taxa_brl")
    out["margem_brl"] = margem.get("margem_brl")
    out["margem_pct"] = margem.get("margem_pct")
    out["lucro_proxy"] = round(margem_brl * max(0, vendidos), 2)
    return out


def top_por_margem(produtos: list[dict[str, Any]], top_n: int = 10) -> list[dict[str, Any]]:
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
