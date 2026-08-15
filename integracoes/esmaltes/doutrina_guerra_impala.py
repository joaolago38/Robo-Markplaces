"""
integracoes/esmaltes/doutrina_guerra_impala.py
Regra de engajamento: guerra por faixa. Só PERL iguala preço.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import DOUTRINA_GUERRA_IMPALA_CATALOGO, ROOT

logger = logging.getLogger("doutrina_guerra_impala")

CLASSIF_IGNORAR = "ignorar"
CLASSIF_DIFERENCIAR = "diferenciar"
CLASSIF_IGUALAR = "igualar_faixa"
CLASSIF_NAO_PERSEGUIR = "nao_perseguir"

_PRIORIDADE = {
    CLASSIF_IGUALAR: 40,
    CLASSIF_NAO_PERSEGUIR: 30,
    CLASSIF_DIFERENCIAR: 20,
    CLASSIF_IGNORAR: 0,
}

_TAXA_ML_PADRAO = 0.18
_MARGEM_FASE_PADRAO = {1: 0.10, 2: 0.18, 3: 0.25}


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def carregar_doutrina(caminho: str | None = None) -> dict[str, Any]:
    path = ROOT / (caminho or DOUTRINA_GUERRA_IMPALA_CATALOGO)
    data = ler_json(path, default={})
    return data if isinstance(data, dict) else {}


def frente_skus(doutrina: dict[str, Any] | None = None) -> set[str]:
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    return {str(s).strip().upper() for s in (d.get("skus_frente") or []) if str(s).strip()}


def sku_preco_guerra(doutrina: dict[str, Any] | None = None) -> str:
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    return str(d.get("sku_preco") or "IMP-PERL-004").strip().upper()


def sku_pode_mexer_preco(sku: str, doutrina: dict[str, Any] | None = None) -> bool:
    """
    PERL é o único IMP-* que iguala preço.
    SKU fora de IMP-/frente (testes genéricos) não é restringido.
    """
    sku_u = (sku or "").strip().upper()
    if not sku_u:
        return False
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    preco = sku_preco_guerra(d)
    if sku_u.startswith("IMP-"):
        return sku_u == preco
    frente = frente_skus(d)
    if sku_u in frente:
        return sku_u == preco
    return True


def piso_preco(produto: dict[str, Any] | None, doutrina: dict[str, Any] | None = None) -> float | None:
    """Preço mínimo da fase: custo / (1 - taxa ML - margem da fase)."""
    if not isinstance(produto, dict):
        return None
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    custo = _f(produto.get("custo_total") or produto.get("custo"))
    if custo <= 0:
        return None
    try:
        fase = int(produto.get("fase_atual") or 1)
    except (TypeError, ValueError):
        fase = 1
    margens = d.get("margem_por_fase") or {}
    margem = _f(margens.get(str(fase)) or margens.get(fase), _MARGEM_FASE_PADRAO.get(fase, 0.10))
    taxa = _f(d.get("taxa_ml"), _TAXA_ML_PADRAO)
    denom = 1.0 - taxa - margem
    if denom <= 0:
        return None
    return round(custo / denom, 2)


def _rival_ao_vivo(comp: dict[str, Any]) -> bool:
    fonte = str(comp.get("fonte_rival") or "").strip().lower()
    if fonte == "ao_vivo":
        return True
    if fonte in ("ausente", "catalogo"):
        return False
    return comp.get("gap_pct") is not None and int(comp.get("rivais_no_tam") or 0) > 0


def _row(
    *,
    sku: str,
    classificacao: str,
    arma: str,
    fazer: str,
    nao_fazer: str,
    motivo: str,
    disparar: bool,
    gap_pct: float,
    rival_min: float | None,
    piso: float | None,
    nosso_preco: float,
    mlb_ok: bool,
    kit_tag: str,
) -> dict[str, Any]:
    return {
        "sku": sku,
        "classificacao": classificacao,
        "arma": arma,
        "fazer": fazer,
        "nao_fazer": nao_fazer,
        "motivo": motivo,
        "disparar": disparar,
        "score": _PRIORIDADE.get(classificacao, 0) + max(0.0, gap_pct),
        "gap_pct": gap_pct,
        "rival_min": rival_min,
        "piso_preco": piso,
        "nosso_preco": nosso_preco,
        "mlb_ok": mlb_ok,
        "kit_tag": kit_tag,
    }


def classificar_golpe(
    comp: dict[str, Any],
    *,
    produto: dict[str, Any] | None = None,
    doutrina: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Um kit da frente → classificação do golpe (ou None se fora da guerra)."""
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    sku = str(comp.get("sku") or "").strip().upper()
    if not sku:
        return None
    frente = frente_skus(d)
    if frente and sku not in frente:
        return None

    gap = comp.get("gap_pct")
    gap_f = _f(gap) if gap is not None else 0.0
    gap_min = _f(d.get("gap_igualar_pct") or (d.get("gatilhos") or {}).get("gap_pct_min"), 3.0)
    rival_min = _f(comp.get("rival_min")) or None
    nosso = _f(comp.get("nosso_preco"))
    mlb_ok = bool(comp.get("mlb_ok"))
    ao_vivo = _rival_ao_vivo(comp)
    piso = piso_preco(produto, d)
    preco_sku = sku_preco_guerra(d)
    kit_tag = str(comp.get("kit_tag") or f"kit:{sku.lower()}")
    base = dict(
        sku=sku,
        gap_pct=gap_f,
        rival_min=rival_min if rival_min and rival_min > 0 else None,
        piso=piso,
        nosso_preco=nosso,
        mlb_ok=mlb_ok,
        kit_tag=kit_tag,
    )

    if not mlb_ok:
        return _row(
            classificacao=CLASSIF_IGNORAR,
            arma="observar",
            fazer="Publicar MLB da frente (decisão do dia) — golpe de preço não se aplica",
            nao_fazer="Reagir a rival sem anúncio próprio; Ads; 2º CNPJ",
            motivo="sem MLB — guerra de preço ainda não começou",
            disparar=False,
            **base,
        )
    if not ao_vivo or gap is None:
        return _row(
            classificacao=CLASSIF_IGNORAR,
            arma="observar",
            fazer="Manter preço e chat. Esperar rival ao vivo no tamanho",
            nao_fazer="Tratar preço de planilha como guerra",
            motivo="sem rival ao vivo no tamanho",
            disparar=False,
            **base,
        )

    rival = _f(rival_min)
    abaixo_do_piso = bool(piso and rival > 0 and rival < piso)

    if sku == preco_sku:
        if abaixo_do_piso:
            return _row(
                classificacao=CLASSIF_NAO_PERSEGUIR,
                arma="observar",
                fazer=f"Manter `{sku}` no piso da fase (R$ {piso:.2f})",
                nao_fazer="Igualar dump abaixo do custo+taxa; mexer MIMO/JUPAES",
                motivo=f"rival R$ {rival:.2f} < piso R$ {piso:.2f}",
                disparar=True,
                **base,
            )
        if gap_f >= gap_min:
            return _row(
                classificacao=CLASSIF_IGUALAR,
                arma="preco",
                fazer=f"Igualar `{sku}` na faixa (nosso R$ {nosso:.2f} vs rival R$ {rival:.2f})",
                nao_fazer="Furar o piso; baixar MIMO; Ads neste golpe",
                motivo=f"gap {gap_f:.1f}% ≥ {gap_min:.0f}% e rival ≥ piso",
                disparar=True,
                **base,
            )
        return _row(
            classificacao=CLASSIF_IGNORAR,
            arma="observar",
            fazer="Nada. Próxima leitura do radar",
            nao_fazer="Repricing no mesmo dia por variação pontual",
            motivo=f"gap {gap_f:.1f}% < {gap_min:.0f}%",
            disparar=False,
            **base,
        )

    if gap_f >= gap_min:
        return _row(
            classificacao=CLASSIF_DIFERENCIAR,
            arma="listing",
            fazer=f"Diferenciar `{sku}` (título/foto/chat) — preço firme",
            nao_fazer="Baixar este SKU; igualar kit 10/15 no prejuízo",
            motivo=f"gap {gap_f:.1f}% — arma é diferencial, não preço",
            disparar=True,
            **base,
        )
    return _row(
        classificacao=CLASSIF_IGNORAR,
        arma="observar",
        fazer="Nada. Chat segue no ciclo 30 min",
        nao_fazer="Abrir 4º SKU; perseguir centavos",
        motivo=f"gap {gap_f:.1f}% sem urgência",
        disparar=False,
        **base,
    )
