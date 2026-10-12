"""core/empresa/apresentacao.py — textos Telegram e bloco Claude (SRP)."""
from __future__ import annotations

from typing import Any

from core.empresa.catalogo import carregar_catalogo, empresa_por_id
from core.empresa.cnpj_utils import digitos, formatar_cnpj
from core.empresa.dono_produtos import situacao_dono_produtos
from core.empresa.flags import flag
from core.empresa.marketplace import norm_marketplace
from core.empresa.roteador import empresa_ativa, resolver_empresa


def marketplace_foco(empresa: dict[str, Any] | None = None) -> str:
    emp = empresa or empresa_ativa()
    if emp:
        return str((emp.get("marketplaces") or {}).get("foco_principal") or "mercadolivre")
    return (
        norm_marketplace(str(flag("MARKETPLACE_FOCO_PRINCIPAL", "mercadolivre") or "mercadolivre"))
        or "mercadolivre"
    )


def prioriza_mercadolivre(empresa: dict[str, Any] | None = None) -> bool:
    return marketplace_foco(empresa) == "mercadolivre"


def mapa_dois_cnpjs() -> dict[str, Any]:
    esm = empresa_por_id("esmaltes_impala") or {}
    dem = empresa_por_id("masterprint") or {}
    dono = situacao_dono_produtos()
    esmaltes_cnpj = digitos(str(flag("ESMALTES_CNPJ", "52668583000127")))
    demais_cnpj = digitos(str(flag("DEMAIS_PRODUTOS_CNPJ", "23811261000197")))
    return {
        "esmaltes": {
            "empresa_id": "esmaltes_impala",
            "cnpj": esm.get("cnpj") or esmaltes_cnpj,
            "cnpj_formatado": esm.get("cnpj_formatado") or formatar_cnpj(esmaltes_cnpj),
            "nome": esm.get("nome_fantasia") or "Impala / esmaltes",
        },
        "demais_produtos": {
            "empresa_id": "masterprint",
            "cnpj": dem.get("cnpj") or demais_cnpj,
            "cnpj_formatado": dem.get("cnpj_formatado") or formatar_cnpj(demais_cnpj),
            "nome": dem.get("nome_fantasia") or "Masterprint / demais produtos",
        },
        "dono_produtos": dono,
    }


def contexto_analise(
    *,
    ramo: str | None = None,
    empresa_id: str | None = None,
) -> dict[str, Any]:
    emp = resolver_empresa(ramo=ramo, empresa_id=empresa_id)
    cat = carregar_catalogo()
    foco = marketplace_foco(emp)
    mapa = mapa_dois_cnpjs()
    dono = situacao_dono_produtos()
    return {
        "ok": emp is not None,
        "foco_marketplace_padrao": cat.get("foco_marketplace_padrao"),
        "foco_marketplace": foco,
        "prioriza_mercadolivre": foco == "mercadolivre",
        "empresa": emp,
        "cnpj": (emp or {}).get("cnpj_formatado") or (emp or {}).get("cnpj") or None,
        "cnaes": (emp or {}).get("cnaes") or [],
        "cnae_principal": (emp or {}).get("cnae_principal"),
        "ramos": (emp or {}).get("ramos") or [],
        "agentes_prioritarios": (emp or {}).get("agentes_prioritarios") or [],
        "dois_cnpjs": mapa,
        "dono_produtos": dono,
        "nota": (
            f"Dados de produtos no CNPJ {dono.get('cnpj_formatado')}. "
            + (
                "Já no CNPJ alvo."
                if dono.get("usando_alvo")
                else f"Migração preparada para {formatar_cnpj(dono.get('cnpj_alvo') or '')}."
            )
            + " Mercado Livre é o foco. Use CNPJ_DONO_PRODUTOS_USAR_ALVO=1 para trocar."
        ),
    }


def linha_empresa_telegram(empresa: dict[str, Any] | None = None) -> str:
    emp = empresa or empresa_ativa()
    if not emp:
        return "Empresa: _não configurada_ · foco *Mercado Livre*"
    partes = [f"Empresa: *{emp.get('nome_fantasia') or emp.get('id')}*"]
    if emp.get("cnpj_formatado"):
        partes.append(f"CNPJ `{emp['cnpj_formatado']}`")
    cnae = emp.get("cnae_principal") or {}
    if cnae.get("codigo"):
        partes.append(f"CNAE `{cnae['codigo']}`")
    foco = marketplace_foco(emp)
    if foco == "mercadolivre":
        partes.append("foco *Mercado Livre*")
    else:
        partes.append(f"foco *{foco}*")
    return " · ".join(partes)
