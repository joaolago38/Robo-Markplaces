"""core/empresa/catalogo.py — catálogo de empresas (SRP)."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT
from core.empresa.cnpj_utils import digitos, formatar_cnpj, norm_cnae
from core.empresa.flags import flag
from core.empresa.marketplace import norm_marketplace

logger = logging.getLogger("empresa_catalogo")


@lru_cache(maxsize=1)
def carregar_catalogo(caminho: str | None = None) -> dict[str, Any]:
    path = ROOT / (caminho or flag("EMPRESAS_CNAE_CNPJ_CATALOGO", "catalogo/empresas_cnae_cnpj.json"))
    data = ler_json(path, default={})
    if not isinstance(data, dict) or not data.get("empresas"):
        try:
            import json

            parsed = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(parsed, dict):
                data = parsed
        except Exception as exc:
            logger.warning("Falha ao ler %s: %s", path, exc)
            data = {}
    if not isinstance(data, dict):
        data = {}
    empresas = [e for e in (data.get("empresas") or []) if isinstance(e, dict)]
    foco_padrao = norm_marketplace(
        data.get("foco_marketplace_padrao")
        or flag("MARKETPLACE_FOCO_PRINCIPAL", "mercadolivre")
        or "mercadolivre"
    )
    return {
        "versao": data.get("versao") or 1,
        "descricao": data.get("descricao") or "",
        "foco_marketplace_padrao": foco_padrao or "mercadolivre",
        "empresa_ativa_id": str(
            flag("EMPRESA_ATIVA_ID", "") or data.get("empresa_ativa_id") or ""
        ).strip(),
        "dono_produtos": data.get("dono_produtos")
        if isinstance(data.get("dono_produtos"), dict)
        else {},
        "empresas": empresas,
        "fonte": str(path),
    }


def limpar_cache_empresas() -> None:
    carregar_catalogo.cache_clear()


def enriquecer_empresa(raw: dict[str, Any], cat: dict[str, Any] | None = None) -> dict[str, Any]:
    from core.config import ML_SITE_ID

    cat = cat or carregar_catalogo()
    eid = str(raw.get("id") or "").strip()
    cnpj = digitos(str(raw.get("cnpj") or ""))
    if not cnpj and eid == "esmaltes_impala":
        cnpj = digitos(str(flag("ESMALTES_CNPJ", "52668583000127")))
    if not cnpj and eid == "masterprint":
        cnpj = digitos(str(flag("DEMAIS_PRODUTOS_CNPJ", "23811261000197")))

    cnaes = []
    for c in raw.get("cnaes") or []:
        if not isinstance(c, dict):
            continue
        codigo = str(c.get("codigo") or "").strip()
        if not codigo:
            continue
        cnaes.append(
            {
                "codigo": codigo,
                "codigo_norm": norm_cnae(codigo),
                "descricao": str(c.get("descricao") or "").strip(),
                "principal": bool(c.get("principal")),
            }
        )
    mk = raw.get("marketplaces") if isinstance(raw.get("marketplaces"), dict) else {}
    foco = norm_marketplace(
        mk.get("foco_principal")
        or cat.get("foco_marketplace_padrao")
        or flag("MARKETPLACE_FOCO_PRINCIPAL", "mercadolivre")
        or "mercadolivre"
    )
    ativos = [norm_marketplace(x) for x in (mk.get("ativos") or ["mercadolivre"])]
    ativos = [a for a in ativos if a]
    if foco and foco not in ativos:
        ativos = [foco, *ativos]
    secundarios = [norm_marketplace(x) for x in (mk.get("secundarios") or [])]
    ml = raw.get("ml") if isinstance(raw.get("ml"), dict) else {}
    shopee = raw.get("shopee") if isinstance(raw.get("shopee"), dict) else {}
    magalu = raw.get("magalu") if isinstance(raw.get("magalu"), dict) else {}
    amazon = raw.get("amazon") if isinstance(raw.get("amazon"), dict) else {}

    return {
        "id": eid,
        "ativo": bool(raw.get("ativo", True)),
        "nome_fantasia": str(raw.get("nome_fantasia") or "").strip(),
        "razao_social": str(raw.get("razao_social") or "").strip(),
        "cnpj": cnpj,
        "cnpj_formatado": formatar_cnpj(cnpj),
        "cnaes": cnaes,
        "cnae_principal": next(
            (c for c in cnaes if c.get("principal")), cnaes[0] if cnaes else None
        ),
        "marketplaces": {
            "foco_principal": foco,
            "ativos": ativos,
            "secundarios": [s for s in secundarios if s],
            "notas": mk.get("notas") or "",
        },
        "ml": {
            "seller_id": str(ml.get("seller_id") or "").strip(),
            "nickname": str(ml.get("nickname") or "").strip(),
            "site_id": str(ml.get("site_id") or ML_SITE_ID or "MLB").strip() or "MLB",
        },
        "shopee": {
            "shop_id": str(shopee.get("shop_id") or "").strip(),
        },
        "magalu": {
            "seller_id": str(magalu.get("seller_id") or magalu.get("merchant_id") or "").strip(),
        },
        "amazon": {
            "seller_id": str(amazon.get("seller_id") or "").strip(),
        },
        "telegram_gestor_chat_id": str(raw.get("telegram_gestor_chat_id") or "").strip(),
        "ramos": [str(r).strip() for r in (raw.get("ramos") or []) if str(r).strip()],
        "agentes_prioritarios": [
            str(a).strip() for a in (raw.get("agentes_prioritarios") or []) if str(a).strip()
        ],
        "notas": raw.get("notas") or "",
        "prioriza_mercadolivre": foco == "mercadolivre",
    }


def listar_empresas(*, apenas_ativas: bool = True) -> list[dict[str, Any]]:
    cat = carregar_catalogo()
    out = []
    for e in cat.get("empresas") or []:
        if apenas_ativas and not e.get("ativo", True):
            continue
        out.append(enriquecer_empresa(e, cat))
    return out


def empresa_por_id(empresa_id: str) -> dict[str, Any] | None:
    eid = str(empresa_id or "").strip()
    if not eid:
        return None
    for e in listar_empresas(apenas_ativas=False):
        if e.get("id") == eid:
            return e
    return None


def empresa_por_cnpj(cnpj: str) -> dict[str, Any] | None:
    alvo = digitos(cnpj)
    if len(alvo) != 14:
        return None
    for e in listar_empresas(apenas_ativas=False):
        if e.get("cnpj") == alvo:
            return e
    return None


def empresas_por_cnae(codigo: str) -> list[dict[str, Any]]:
    alvo = norm_cnae(codigo)
    if not alvo:
        return []
    out = []
    for e in listar_empresas(apenas_ativas=True):
        for c in e.get("cnaes") or []:
            if c.get("codigo_norm") == alvo or alvo in str(c.get("codigo_norm") or ""):
                out.append(e)
                break
    return out


def empresa_por_ramo(ramo: str) -> dict[str, Any] | None:
    alvo = str(ramo or "").strip().lower()
    if not alvo:
        return None
    for e in listar_empresas(apenas_ativas=True):
        ramos = [str(r).lower() for r in (e.get("ramos") or [])]
        if alvo in ramos:
            return e
    return None
