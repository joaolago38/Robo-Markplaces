"""
core/marketplace_cnpj.py
Identifica qual CNPJ (Impala vs Masterprint) está por trás da conta
conectada em cada marketplace.

Uma secret global (ML_SELLER_ID, SHOPEE_SHOP_ID, …) é casada com o
seller/shop gravado em cada empresa do catálogo. Se os dois CNPJs
apontam para o mesmo ID, o resultado é ambíguo — o ponto cego original.

A conta usada para publicar é a do CNPJ dono do produto, não a secret
global. Masterprint só autentica com token próprio.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from core.empresa.cnpj_utils import formatar_cnpj
from core.empresa.marketplace import norm_marketplace


def _conta_id_env(marketplace: str) -> str:
    from core import config as cfg

    mp = norm_marketplace(marketplace)
    if mp == "mercadolivre":
        return str(getattr(cfg, "ML_SELLER_ID", "") or "").strip()
    if mp == "shopee":
        return str(getattr(cfg, "SHOPEE_SHOP_ID", "") or "").strip()
    if mp == "magalu":
        return str(getattr(cfg, "MAGALU_SELLER_ID", "") or "").strip()
    if mp == "amazon":
        return str(getattr(cfg, "AMAZON_SELLER_ID", "") or "").strip()
    return ""


def _conta_id_empresa(empresa: dict[str, Any], marketplace: str) -> str:
    mp = norm_marketplace(marketplace)
    bloco = empresa.get(mp) if isinstance(empresa.get(mp), dict) else {}
    if mp == "mercadolivre":
        bloco = empresa.get("ml") if isinstance(empresa.get("ml"), dict) else bloco
        return str(bloco.get("seller_id") or "").strip()
    if mp == "shopee":
        return str(bloco.get("shop_id") or "").strip()
    if mp == "magalu":
        return str(bloco.get("seller_id") or bloco.get("merchant_id") or "").strip()
    if mp == "amazon":
        return str(bloco.get("seller_id") or "").strip()
    return ""


def identificar_cnpj_conectado(
    marketplace: str,
    conta_id: str | None = None,
) -> dict[str, Any]:
    """Casa a conta autenticada com Impala ou Masterprint."""
    from core.empresa.catalogo import listar_empresas
    from core.empresa.overrides import aplicar_overrides_env

    mp = norm_marketplace(marketplace) or str(marketplace or "").strip().lower()
    live = str(conta_id or "").strip() or _conta_id_env(mp)
    empresas = [aplicar_overrides_env(e) for e in listar_empresas(apenas_ativas=True)]

    hits: list[dict[str, Any]] = []
    for emp in empresas:
        eid_cat = _conta_id_empresa(emp, mp)
        if live and eid_cat and live == eid_cat:
            hits.append(emp)

    base = {
        "marketplace": mp,
        "conta_id": live,
        "identificado": False,
        "ambiguo": False,
        "empresa_id": "",
        "cnpj": "",
        "cnpj_formatado": "",
        "nome_fantasia": "",
        "confianca": "nao_identificado",
        "motivo": "",
    }

    if not live:
        base["motivo"] = (
            "conta do canal vazia — preencha seller/shop no catálogo ou no env "
            "para saber qual CNPJ está conectado"
        )
        return base

    if len(hits) > 1:
        nomes = [str(h.get("nome_fantasia") or h.get("id")) for h in hits]
        cnpjs = [str(h.get("cnpj_formatado") or h.get("cnpj")) for h in hits]
        base.update(
            {
                "ambiguo": True,
                "confianca": "ambiguo",
                "motivo": (
                    f"a mesma conta {live} está nos CNPJs {', '.join(cnpjs)} "
                    f"({', '.join(nomes)}) — separe seller/shop por empresa"
                ),
                "candidatos": [
                    {"empresa_id": h.get("id"), "cnpj": h.get("cnpj"), "nome": h.get("nome_fantasia")}
                    for h in hits
                ],
            }
        )
        return base

    if len(hits) == 1:
        h = hits[0]
        return {
            **base,
            "identificado": True,
            "empresa_id": str(h.get("id") or ""),
            "cnpj": str(h.get("cnpj") or ""),
            "cnpj_formatado": str(h.get("cnpj_formatado") or formatar_cnpj(str(h.get("cnpj") or ""))),
            "nome_fantasia": str(h.get("nome_fantasia") or ""),
            "confianca": "vinculo_explicito",
            "motivo": f"conta {live} casa com {h.get('nome_fantasia') or h.get('id')}",
        }

    base["motivo"] = (
        f"conta {live} não casa com seller/shop de Impala nem Masterprint — "
        "grave o ID no catálogo da empresa dona desta conta"
    )
    return base


_TOKENS_MASTERPRINT = {
    "mercadolivre": ("ML_ACCESS_TOKEN_MASTERPRINT",),
    "shopee": ("SHOPEE_ACCESS_TOKEN_MASTERPRINT",),
    "magalu": ("MAGALU_ACCESS_TOKEN_MASTERPRINT",),
    "amazon": ("AMAZON_ACCESS_TOKEN_MASTERPRINT",),
}

_ATIVA: ContextVar[dict[str, Any] | None] = ContextVar("conta_cnpj_ativa", default=None)


def _token_masterprint(marketplace: str) -> str:
    import core.config as cfg

    mp = norm_marketplace(marketplace)
    for nome in _TOKENS_MASTERPRINT.get(mp, ()):
        vivo = os.getenv(nome, "").strip()
        if vivo:
            return vivo
        fixo = str(getattr(cfg, nome, "") or "").strip()
        if fixo:
            return fixo
    return ""


def credenciais_da_empresa(empresa_id: str, marketplace: str) -> dict[str, Any]:
    """Conta e token do CNPJ pedido. Não cai na secret da outra empresa."""
    from core.empresa.catalogo import listar_empresas
    from core.empresa.overrides import aplicar_overrides_env

    mp = norm_marketplace(marketplace) or str(marketplace or "").strip().lower()
    eid = str(empresa_id or "").strip()
    empresas = [aplicar_overrides_env(e) for e in listar_empresas(apenas_ativas=True)]
    alvo = next((e for e in empresas if str(e.get("id") or "") == eid), None)
    conta = _conta_id_empresa(alvo or {}, mp)
    outros = [
        _conta_id_empresa(e, mp)
        for e in empresas
        if str(e.get("id") or "") != eid and _conta_id_empresa(e, mp)
    ]
    compartilhada = bool(conta and conta in outros)
    token = _token_masterprint(mp) if eid == "masterprint" else ""
    return {
        "empresa_id": eid,
        "marketplace": mp,
        "cnpj": str((alvo or {}).get("cnpj") or ""),
        "cnpj_formatado": str((alvo or {}).get("cnpj_formatado") or ""),
        "nome_fantasia": str((alvo or {}).get("nome_fantasia") or ""),
        "conta_id": "" if compartilhada else conta,
        "conta_bruta": conta,
        "access_token": "" if compartilhada else token,
        "compartilhada": compartilhada,
        "token_presente": bool(token) if eid == "masterprint" else True,
    }


def conta_em_uso(marketplace: str) -> dict[str, Any] | None:
    """Credencial empilhada por usar_conta, se for deste canal."""
    atual = _ATIVA.get()
    if not isinstance(atual, dict):
        return None
    mp = norm_marketplace(marketplace)
    if norm_marketplace(str(atual.get("marketplace") or "")) != mp:
        return None
    return atual


@contextmanager
def usar_conta(credencial: dict[str, Any] | None) -> Iterator[dict[str, Any]]:
    """Troca seller/token do canal enquanto o bloco roda. Impala fica no client padrão."""
    cred = credencial if isinstance(credencial, dict) else {}
    if cred.get("empresa_id") == "esmaltes_impala" or not str(cred.get("conta_id") or "").strip():
        yield cred
        return
    token = _ATIVA.set(cred)
    try:
        yield cred
    finally:
        _ATIVA.reset(token)


def linha_cnpj_telegram(ident: dict[str, Any]) -> str:
    if ident.get("ambiguo"):
        return f"CNPJ: AMBÍGUO — {ident.get('motivo')}"
    if ident.get("identificado"):
        nome = ident.get("nome_fantasia") or ident.get("empresa_id")
        cnpj = ident.get("cnpj_formatado") or ident.get("cnpj")
        return f"CNPJ: {nome} ({cnpj}) · conta {ident.get('conta_id')}"
    return f"CNPJ: não identificado · {ident.get('motivo') or 'sem conta'}"
