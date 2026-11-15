"""
core/empresa/publicacao_cnpj.py
Trava de publicação: o SKU só sai na empresa cujo CNAE cobre o ramo.
Masterprint permanece fechada até o veredito de ruptura da Impala ser liberado.
"""
from __future__ import annotations

from typing import Any

from core.empresa.cnpj_utils import norm_cnae
from core.empresa.marketplace import norm_marketplace

# Prefixo de SKU → ramo do catálogo de empresas.
_PREFIXO_RAMO: tuple[tuple[str, str], ...] = (
    ("IMP-", "esmaltes"),
    ("ANITA", "anita"),
    ("ACET", "acetona"),
    ("REM", "removedores"),
    ("231020", "petg"),
    ("309040", "escritorio"),
    ("309050", "escritorio"),
    ("316010", "escritorio"),
    ("328010", "escritorio"),
)

# Ramo → CNAE normalizado que precisa estar na empresa dona.
_CNAE_DO_RAMO = {
    "esmaltes": "4772500",
    "manicures": "4772500",
    "impala": "4772500",
    "anita": "4772500",
    "acetona": "4772500",
    "removedores": "4772500",
    "filamentos": "4689302",
    "petg": "4689302",
    "masterprint": "4751201",
    "escritorio": "4761003",
    "papelaria": "4761003",
    "demais_produtos": "4751201",
}


def ramo_do_sku(sku: str) -> str:
    s = str(sku or "").strip().upper()
    for prefixo, ramo in _PREFIXO_RAMO:
        if s.startswith(prefixo):
            return ramo
    return ""


def _cnaes(empresa: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for c in empresa.get("cnaes") or []:
        if isinstance(c, dict):
            n = norm_cnae(str(c.get("codigo_norm") or c.get("codigo") or ""))
        else:
            n = norm_cnae(str(c))
        if n:
            out.add(n)
    return out


def _veredito_ruptura(explicito: str | None) -> str:
    if explicito is not None:
        return str(explicito or "").strip().lower()
    try:
        from integracoes.empresa.ponto_ruptura_segundo_cnpj import avaliar_ponto_ruptura

        return str((avaliar_ponto_ruptura() or {}).get("veredito") or "ainda_nao")
    except Exception:
        return "ainda_nao"


def autorizar_publicacao(
    sku: str,
    *,
    marketplace: str = "mercadolivre",
    empresa_id: str | None = None,
    veredito: str | None = None,
) -> dict[str, Any]:
    """
    Recusa esmalte na Masterprint, PETG na Impala, conta compartilhada
    e qualquer publicação Masterprint antes de veredito=liberado.
    """
    from core.empresa.catalogo import empresa_por_ramo
    from core.marketplace_cnpj import credenciais_da_empresa

    mp = norm_marketplace(marketplace) or "mercadolivre"
    ramo = ramo_do_sku(sku)
    base: dict[str, Any] = {
        "ok": False,
        "motivo": "",
        "sku": str(sku or "").strip().upper(),
        "ramo": ramo,
        "marketplace": mp,
        "empresa_id": "",
        "cnpj": "",
        "conta_id": "",
        "access_token": "",
        "token_presente": False,
        "compartilhada": False,
    }
    if not ramo:
        base["motivo"] = "ramo_desconhecido"
        return base

    dona = empresa_por_ramo(ramo) or {}
    eid = str(dona.get("id") or "")
    base["empresa_id"] = eid
    base["cnpj"] = str(dona.get("cnpj") or "")
    pedido = str(empresa_id or "").strip()
    if pedido and pedido != eid:
        base["motivo"] = "cnpj_errado"
        base["empresa_id"] = pedido
        return base
    if not eid:
        base["motivo"] = "cnae_nao_cobre"
        return base

    exigido = _CNAE_DO_RAMO.get(ramo, "")
    if exigido and exigido not in _cnaes(dona):
        base["motivo"] = "cnae_nao_cobre"
        return base

    if eid == "masterprint" and _veredito_ruptura(veredito) != "liberado":
        base["motivo"] = "ruptura_impala"
        return base

    cred = credenciais_da_empresa(eid, mp)
    base["conta_id"] = str(cred.get("conta_id") or "")
    base["access_token"] = str(cred.get("access_token") or "")
    base["token_presente"] = bool(cred.get("token_presente"))
    base["compartilhada"] = bool(cred.get("compartilhada"))
    if cred.get("compartilhada"):
        base["motivo"] = "conta_compartilhada"
        base["conta_id"] = ""
        base["access_token"] = ""
        return base
    if not base["conta_id"]:
        base["motivo"] = "sem_conta"
        return base

    base["ok"] = True
    base["motivo"] = "ok"
    return base
