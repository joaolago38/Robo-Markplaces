"""
core/empresa/roteador.py — Strategy: propósito da análise → empresa/CNPJ.
"""
from __future__ import annotations

from typing import Any

from core.empresa.catalogo import (
    carregar_catalogo,
    empresa_por_cnpj,
    empresa_por_id,
    empresa_por_ramo,
    listar_empresas,
)
from core.empresa.flags import flag
from core.empresa.overrides import aplicar_overrides_env

# Strategy table: palavras-chave → empresa_id
_ESTRATEGIAS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "masterprint",
            "filamento",
            "escritorio",
            "petg",
            "demais",
            "apagador",
            "pincel",
        ),
        "masterprint",
    ),
    (
        (
            "esmalte",
            "acetona",
            "removedor",
            "manicure",
            "impala",
            "anita",
            "kit",
            "operacao",
            "crescimento",
            "decisao",
            "ecossistema",
            "listing",
            "sintese_ml",
        ),
        "esmaltes_impala",
    ),
)


def empresa_ativa() -> dict[str, Any] | None:
    # Via Facade para respeitar @patch nos testes (empresa_por_cnpj / EMPRESA_ATIVA_*)
    import core.empresa_contexto as ec

    cat = carregar_catalogo()
    if ec.EMPRESA_ATIVA_CNPJ:
        achada = ec.empresa_por_cnpj(str(ec.EMPRESA_ATIVA_CNPJ))
        if achada:
            return aplicar_overrides_env(achada)
    eid = str(ec.EMPRESA_ATIVA_ID or cat.get("empresa_ativa_id") or "").strip()
    if eid:
        achada = ec.empresa_por_id(eid)
        if achada:
            return aplicar_overrides_env(achada)
    empresas = listar_empresas(apenas_ativas=True)
    if not empresas:
        return None
    return aplicar_overrides_env(empresas[0])


def empresa_para_proposito(proposito: str | None) -> dict[str, Any] | None:
    """Roteia análise Claude/agente para o CNPJ certo (Strategy)."""
    p = str(proposito or "").strip().lower()
    for chaves, empresa_id in _ESTRATEGIAS:
        if any(k in p for k in chaves):
            emp = empresa_por_id(empresa_id)
            return aplicar_overrides_env(emp) if emp else None
    return empresa_ativa()


def resolver_empresa(
    *,
    ramo: str | None = None,
    empresa_id: str | None = None,
) -> dict[str, Any] | None:
    """Chain of responsibility simples: id → ramo → ativa."""
    if empresa_id:
        emp = empresa_por_id(empresa_id)
        if emp:
            return emp
    if ramo:
        emp = empresa_por_ramo(ramo)
        if emp:
            return emp
    return empresa_ativa()
