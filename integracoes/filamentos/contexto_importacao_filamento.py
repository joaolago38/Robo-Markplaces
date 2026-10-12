"""
integracoes/filamentos/contexto_importacao_filamento.py
Contexto de importação específico para filamento 3D (Masterprint).

Aplica as regras atualizadas:
  - CEP destino teste/padrão 13467-694
  - CNPJ Masterprint + CNAE × marketplaces
  - Siscomex Portaria ME 4.131/2021 (DI + adições)
  - AFRMM no marítimo · PIS/COFINS · ICMS por dentro
"""
from __future__ import annotations

from typing import Any

from core.config import (
    DEMAIS_PRODUTOS_CNPJ,
    FILAMENTOS_IMPORTACAO_CNPJ,
    FILAMENTOS_SOURCING_ICMS_PCT,
    FILAMENTOS_SOURCING_II_PCT,
    FILAMENTOS_SOURCING_IPI_PCT,
    FILAMENTOS_SOURCING_NCM,
    IMPORTACAO_AFRMM_PCT,
    IMPORTACAO_COFINS_PCT,
    IMPORTACAO_DESEMBARACO_BRL,
    IMPORTACAO_DESTINO_CEP,
    IMPORTACAO_PIS_PCT,
    IMPORTACAO_SISCOMEX_ADICOES,
    MASTERPRINT_CNPJ,
)
from integracoes.importacao.contexto_importacao_cnpj import (
    CEP_TESTE_PADRAO,
    anexar_contexto_ao_resultado,
    formatar_bloco_telegram_contexto,
)
from integracoes.importacao.siscomex import calcular_taxa_siscomex, taxa_siscomex_brl

CNPJ_FILAMENTO = (
    FILAMENTOS_IMPORTACAO_CNPJ or MASTERPRINT_CNPJ or DEMAIS_PRODUTOS_CNPJ or "23811261000197"
).strip()


def cep_destino_filamento() -> str:
    return (IMPORTACAO_DESTINO_CEP or CEP_TESTE_PADRAO or "13467-694").strip()


def params_landed_filamento(
    produto: dict[str, Any] | None = None,
    *,
    adicoes: int | None = None,
) -> dict[str, Any]:
    """Parâmetros tributários/despesas para custo_landed de filamento 3D."""
    p = produto if isinstance(produto, dict) else {}

    def _f(chave: str, padrao: float) -> float:
        v = p.get(chave)
        if v is None:
            return padrao
        try:
            return float(v)
        except (TypeError, ValueError):
            return padrao

    n_ad = adicoes
    if n_ad is None:
        try:
            n_ad = int(p.get("siscomex_adicoes") or IMPORTACAO_SISCOMEX_ADICOES or 1)
        except (TypeError, ValueError):
            n_ad = 1
    n_ad = max(1, int(n_ad))
    sis = calcular_taxa_siscomex(adicoes=n_ad)

    return {
        "ii_pct": _f("ii_pct", FILAMENTOS_SOURCING_II_PCT),
        "ipi_pct": _f("ipi_pct", FILAMENTOS_SOURCING_IPI_PCT),
        "pis_pct": IMPORTACAO_PIS_PCT,
        "cofins_pct": IMPORTACAO_COFINS_PCT,
        "icms_pct": _f("icms_pct", FILAMENTOS_SOURCING_ICMS_PCT),
        "siscomex_brl": float(sis["total_brl"]),
        "siscomex_adicoes": n_ad,
        "siscomex_detalhe": sis,
        "desembaraco_brl": _f("desembaraco_brl", IMPORTACAO_DESEMBARACO_BRL),
        "afrmm_pct": float(IMPORTACAO_AFRMM_PCT),
        "ncm": str(p.get("ncm") or FILAMENTOS_SOURCING_NCM),
        "cnpj_importador": CNPJ_FILAMENTO,
        "cep_destino": cep_destino_filamento(),
    }


def enriquecer_produto_filamento_alibaba(produto: dict[str, Any]) -> dict[str, Any]:
    """Garante campos de importação CNPJ/CEP/Siscomex no item do catálogo."""
    out = dict(produto or {})
    params = params_landed_filamento(out)
    out.setdefault("cnpj_importador", CNPJ_FILAMENTO)
    out.setdefault("empresa_id", "masterprint")
    out.setdefault("ramo", "filamentos")
    out.setdefault("cep_destino", cep_destino_filamento())
    out.setdefault("siscomex_adicoes", params["siscomex_adicoes"])
    out.setdefault("ncm", params["ncm"])
    out["siscomex_brl"] = params["siscomex_brl"]
    out["importacao_params"] = {
        k: params[k]
        for k in (
            "ii_pct",
            "ipi_pct",
            "pis_pct",
            "cofins_pct",
            "icms_pct",
            "siscomex_brl",
            "siscomex_adicoes",
            "desembaraco_brl",
            "afrmm_pct",
            "cep_destino",
            "cnpj_importador",
        )
    }
    return out


def anexar_contexto_filamento(
    resultado: dict[str, Any],
    *,
    calculo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = anexar_contexto_ao_resultado(
        resultado,
        calculo=calculo,
        cnpj=CNPJ_FILAMENTO,
    )
    ctx = dict(out.get("contexto_importacao_cnpj") or {})
    ctx["ramo"] = "filamentos_3d"
    cep = dict(ctx.get("cep") or {})
    cep["destino_cep"] = cep_destino_filamento()
    cep["usando_cep_teste"] = cep_destino_filamento() == CEP_TESTE_PADRAO
    ctx["cep"] = cep
    ctx["filamento"] = {
        "ncm_padrao": FILAMENTOS_SOURCING_NCM,
        "ii_pct_padrao": FILAMENTOS_SOURCING_II_PCT,
        "ipi_pct_padrao": FILAMENTOS_SOURCING_IPI_PCT,
        "siscomex_1_adicao_brl": taxa_siscomex_brl(adicoes=1),
        "materiais": ["TPU", "PLA", "PETG", "ABS"],
    }
    out["contexto_importacao_cnpj"] = ctx
    out["bloco_telegram_importacao_cnpj"] = formatar_bloco_telegram_contexto(ctx)
    return out
