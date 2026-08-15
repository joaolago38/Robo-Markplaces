"""
integracoes/ml/filtro_anuncios_conta.py
Ignora anúncios fora do foco (bolsas Mariart / legado) na conta ML autenticada.

A reputação (cor verde, claims, vendas completadas) continua da conta.
Só o catálogo operacional (listar_meus_anuncios e derivados) é filtrado.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT

logger = logging.getLogger("filtro_anuncios_conta")

CATALOGO_PATH = ROOT / "catalogo" / "ml_anuncios_ignorar.json"

_ultimo_filtro: dict[str, Any] = {
    "ignorados": 0,
    "mantidos": 0,
    "motivos": [],
}


def reset_ultimo_filtro() -> None:
    _ultimo_filtro.clear()
    _ultimo_filtro.update({"ignorados": 0, "mantidos": 0, "motivos": []})


def ultimo_filtro_anuncios() -> dict[str, Any]:
    return dict(_ultimo_filtro)


def carregar_regras_ignorar() -> dict[str, Any]:
    raw = ler_json(CATALOGO_PATH, default={})
    return raw if isinstance(raw, dict) else {}


def _norm(val: Any) -> str:
    return str(val or "").strip().lower()


def sku_do_foco(sku: str, prefixos: list[str] | None = None) -> bool:
    u = str(sku or "").strip().upper()
    if not u:
        return False
    prefs = prefixos or ["IMP-", "CRZ-", "BUNDLE-"]
    return any(u.startswith(str(p).upper()) for p in prefs if p)


def _titulo_bate(titulo: str, trechos: list[str]) -> str | None:
    t = _norm(titulo)
    if not t:
        return None
    for trecho in trechos:
        n = _norm(trecho)
        if n and n in t:
            return n
    return None


def anuncio_fora_do_foco(
    anuncio: dict[str, Any],
    regras: dict[str, Any] | None = None,
) -> str | None:
    """Motivo se deve ignorar; None se permanece no radar operacional."""
    regras = regras if regras is not None else carregar_regras_ignorar()
    if not regras.get("ativo", True):
        return None
    sku = str(anuncio.get("sku") or "")
    prefixos = [str(p) for p in (regras.get("sku_prefixos_foco") or []) if p]
    if sku_do_foco(sku, prefixos or None):
        return None

    titulo = str(anuncio.get("titulo") or anuncio.get("family_name") or "")
    sku_l = _norm(sku)
    for trecho in regras.get("sku_contem") or []:
        n = _norm(trecho)
        if n and n in sku_l:
            return f"sku:{n}"

    cat = str(anuncio.get("category_id") or "").strip().upper()
    cats = {str(c).strip().upper() for c in (regras.get("category_ids") or []) if c}
    if cat and cat in cats:
        return f"categoria:{cat}"

    hit = _titulo_bate(titulo, list(regras.get("titulo_contem") or []))
    if hit:
        return f"titulo:{hit}"
    hit = _titulo_bate(titulo, list(regras.get("titulo_legado") or []))
    if hit:
        return f"legado:{hit}"
    return None


def filtrar_anuncios_foco(
    anuncios: list[dict[str, Any]] | None,
    *,
    regras: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Separa anúncios do foco vs bolsas/legado. Nunca lança."""
    regras = regras if regras is not None else carregar_regras_ignorar()
    origem = [a for a in (anuncios or []) if isinstance(a, dict)]
    if not regras.get("ativo", True):
        stats = {"ignorados": 0, "mantidos": len(origem), "motivos": []}
        _ultimo_filtro.update(stats)
        return origem, stats

    mantidos: list[dict[str, Any]] = []
    motivos: list[dict[str, str]] = []
    for a in origem:
        motivo = anuncio_fora_do_foco(a, regras)
        if motivo:
            motivos.append(
                {
                    "item_id": str(a.get("item_id") or ""),
                    "motivo": motivo,
                }
            )
            continue
        mantidos.append(a)
    stats = {
        "ignorados": len(motivos),
        "mantidos": len(mantidos),
        "motivos": motivos[:40],
    }
    _ultimo_filtro.clear()
    _ultimo_filtro.update(stats)
    if stats["ignorados"]:
        logger.info(
            "ML foco: ignorados %s anúncio(s) fora do catálogo (bolsas/legado); %s no radar",
            stats["ignorados"],
            stats["mantidos"],
        )
    return mantidos, stats


def filtrar_anuncios_legado(
    anuncios: list[dict[str, Any]] | None,
    *,
    regras: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Inverso do foco: só bolsas/legado. Não altera o filtro operacional."""
    regras = regras if regras is not None else carregar_regras_ignorar()
    origem = [a for a in (anuncios or []) if isinstance(a, dict)]
    legado: list[dict[str, Any]] = []
    for a in origem:
        if anuncio_fora_do_foco(a, regras):
            legado.append(a)
    stats = {
        "legado": len(legado),
        "foco": len(origem) - len(legado),
    }
    return legado, stats


def palavras_nao_transferir(regras: dict[str, Any] | None = None) -> list[str]:
    """Palavras de bolsa/legado que não podem ir para título Impala."""
    regras = regras if regras is not None else carregar_regras_ignorar()
    out: list[str] = []
    seen: set[str] = set()
    for chave in ("titulo_contem", "sku_contem", "titulo_legado"):
        for raw in regras.get(chave) or []:
            n = _norm(raw)
            if n and n not in seen:
                seen.add(n)
                out.append(n)
    return out
