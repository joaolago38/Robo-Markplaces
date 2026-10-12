"""
Momentos certos de Claude na análise ML: só quando há SKU Impala com
lucro (margem ≥ piso) travado em MLB/estoque — não no heartbeat.

Não publica anúncio. CNPJ 52.668.583/0001-27.
"""
from __future__ import annotations

import logging
from typing import Any

from core.config import MARGEM_MINIMA
from core.datadog_metrics import gauge, incrementar

logger = logging.getLogger("claude_lucro_ml")

PISO = float(MARGEM_MINIMA)


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def momento_lucro_ml(
    *,
    produtos: dict[str, Any] | None = None,
    kits_manicure: dict[str, Any] | None = None,
    acoes: dict[str, Any] | None = None,
    veredito: str = "",
) -> dict[str, Any]:
    """True quando a análise ML muda lucro (não vigia/orquestrador)."""
    prods = produtos if isinstance(produtos, dict) else {}
    kits = kits_manicure if isinstance(kits_manicure, dict) else {}
    agir = acoes if isinstance(acoes, dict) else {}
    candidatos = [c for c in (prods.get("candidatos_margem") or []) if isinstance(c, dict)]
    seguros = [c for c in (prods.get("seguros") or []) if isinstance(c, dict)]
    condicao = [c for c in (kits.get("ofertas_condicao") or []) if isinstance(c, dict)]
    top_agir = [c for c in (agir.get("top") or []) if isinstance(c, dict)]
    publicar = [
        r
        for r in top_agir
        if str(r.get("acao") or "") == "publicar_mlb" and r.get("critica")
    ]

    sku = ""
    margem = 0.0
    motivo = "sem_sku_lucro"
    if condicao:
        top = condicao[0]
        sku = str(top.get("sku") or "")
        margem = _f(top.get("margem_pct"))
        motivo = "kit_manicure_condicao"
    elif candidatos:
        top = candidatos[0]
        sku = str(top.get("sku") or "")
        margem = _f(top.get("margem_real_pct"))
        motivo = "candidato_margem_sem_mlb_estoque"
    elif seguros:
        top = seguros[0]
        sku = str(top.get("sku") or "")
        margem = _f(top.get("margem_real_pct"))
        motivo = "produto_seguro"
    elif publicar:
        sku = str(publicar[0].get("sku") or "")
        motivo = "batalha_publicar_mlb"

    momento = bool(sku) and (
        margem >= PISO or motivo in ("kit_manicure_condicao", "batalha_publicar_mlb", "produto_seguro")
    )
    if str(veredito or "") in ("aproximando", "liberado"):
        momento = True
        motivo = motivo if sku else f"veredito_{veredito}"

    out = {
        "momento": momento,
        "motivo": motivo if momento else "sem_decisao_de_lucro",
        "sku_lucro": sku if momento else "",
        "margem_pct": round(margem, 2) if momento else 0.0,
        "piso_pct": PISO,
    }
    gauge("claude.lucro.momento", 1.0 if momento else 0.0)
    if momento:
        incrementar("claude.lucro.momentos")
    return out


def sintetizar_lucro_ml(
    contexto: dict[str, Any],
    fallback: str,
    *,
    momento: dict[str, Any] | None = None,
) -> str:
    """Claude moderado só no momento de lucro. Não inventa número."""
    from core.claude_ml.dosagem import SYSTEM_RUPTURA
    from core.config import CLAUDE_LUCRO_ML_MOMENTOS
    from core.resumo_ia import sintetizar_claude

    info = momento or {}
    if not CLAUDE_LUCRO_ML_MOMENTOS or not info.get("momento"):
        return ""
    sku = info.get("sku_lucro") or "n/d"
    return sintetizar_claude(
        (
            "Analista de lucro Impala no Mercado Livre. Uso moderado. "
            f"SKU âncora `{sku}` margem `{info.get('margem_pct')}%` "
            f"(piso {info.get('piso_pct')}%). "
            "Em até 6 linhas cite SOMENTE o JSON: "
            "(1) FAZER este SKU (MLB+estoque) se margem ≥ piso; "
            "(2) NÃO FAZER Ads, SORT-006 se margem < piso, 2º CNPJ; "
            "(3) NÃO FAZER kits com margem negativa. "
            "Não invente vd/dia nem ranking. Não publicar anúncio. "
            "CNPJ 52.668.583/0001-27."
        ),
        contexto,
        fallback,
        max_tokens=220,
        origem="lucro_ml_ruptura",
        enriquecer_ml=True,
        proposito="lucro_ml_ruptura_moderada",
        forcar_profundidade="padrao",
        forcar_chamada=True,
        system=SYSTEM_RUPTURA,
        somente_ia=True,
    )
