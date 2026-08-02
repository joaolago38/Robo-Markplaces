"""
core/empresa_contexto.py
Configuração por CNPJ + CNAEs para direcionar análises.

- Mercado Livre é o foco principal por enquanto (foco_marketplace_padrao).
- Não substitui ML_*, MASTERPRINT_*, Telegram nem catálogos já existentes:
  env e configs atuais têm prioridade; este módulo complementa e organiza por empresa/ramo.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

from core.atomic_io import ler_json
from core.config import (
    ML_SELLER_ID,
    ML_SITE_ID,
    ROOT,
    TELEGRAM_GESTOR_CHAT_ID,
)
import core.config as _cfg

# Fail-soft se config antigo no CI sem as novas chaves
EMPRESAS_CNAE_CNPJ_CATALOGO = getattr(
    _cfg, "EMPRESAS_CNAE_CNPJ_CATALOGO", "catalogo/empresas_cnae_cnpj.json"
)
EMPRESA_ATIVA_ID = getattr(_cfg, "EMPRESA_ATIVA_ID", "") or ""
EMPRESA_ATIVA_CNPJ = getattr(_cfg, "EMPRESA_ATIVA_CNPJ", "") or ""
ESMALTES_CNPJ = getattr(_cfg, "ESMALTES_CNPJ", "52668583000127") or "52668583000127"
DEMAIS_PRODUTOS_CNPJ = (
    getattr(_cfg, "DEMAIS_PRODUTOS_CNPJ", "23811261000197") or "23811261000197"
)
CNPJ_DONO_PRODUTOS = (
    getattr(_cfg, "CNPJ_DONO_PRODUTOS", ESMALTES_CNPJ) or ESMALTES_CNPJ
)
CNPJ_DONO_PRODUTOS_ALVO = (
    getattr(_cfg, "CNPJ_DONO_PRODUTOS_ALVO", DEMAIS_PRODUTOS_CNPJ) or DEMAIS_PRODUTOS_CNPJ
)
CNPJ_DONO_PRODUTOS_USAR_ALVO = bool(getattr(_cfg, "CNPJ_DONO_PRODUTOS_USAR_ALVO", False))
MARKETPLACE_FOCO_PRINCIPAL = (
    getattr(_cfg, "MARKETPLACE_FOCO_PRINCIPAL", "mercadolivre") or "mercadolivre"
)

logger = logging.getLogger("empresa_contexto")

_RE_DIG = re.compile(r"\D+")

MARKETPLACES_CONHECIDOS = frozenset(
    {"mercadolivre", "shopee", "magalu", "amazon", "loja_propria"}
)


def _digitos(valor: str) -> str:
    return _RE_DIG.sub("", str(valor or ""))


def formatar_cnpj(cnpj: str) -> str:
    d = _digitos(cnpj)
    if len(d) != 14:
        return d or ""
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _norm_cnae(codigo: str) -> str:
    return re.sub(r"[^0-9]", "", str(codigo or ""))


def _norm_marketplace(nome: str) -> str:
    n = str(nome or "").strip().lower().replace(" ", "").replace("-", "")
    aliases = {
        "ml": "mercadolivre",
        "mercadolivre": "mercadolivre",
        "mercadolibre": "mercadolivre",
        "mlb": "mercadolivre",
        "shopee": "shopee",
        "magalu": "magalu",
        "magazinevoce": "magalu",
        "amazon": "amazon",
        "loja": "loja_propria",
        "lojapropria": "loja_propria",
    }
    return aliases.get(n, n)


@lru_cache(maxsize=1)
def carregar_catalogo(caminho: str | None = None) -> dict[str, Any]:
    path = ROOT / (caminho or EMPRESAS_CNAE_CNPJ_CATALOGO)
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
    foco_padrao = _norm_marketplace(
        data.get("foco_marketplace_padrao") or MARKETPLACE_FOCO_PRINCIPAL or "mercadolivre"
    )
    return {
        "versao": data.get("versao") or 1,
        "descricao": data.get("descricao") or "",
        "foco_marketplace_padrao": foco_padrao or "mercadolivre",
        "empresa_ativa_id": str(
            EMPRESA_ATIVA_ID or data.get("empresa_ativa_id") or ""
        ).strip(),
        "dono_produtos": data.get("dono_produtos")
        if isinstance(data.get("dono_produtos"), dict)
        else {},
        "empresas": empresas,
        "fonte": str(path),
    }


def limpar_cache_empresas() -> None:
    carregar_catalogo.cache_clear()


def listar_empresas(*, apenas_ativas: bool = True) -> list[dict[str, Any]]:
    cat = carregar_catalogo()
    out = []
    for e in cat.get("empresas") or []:
        if apenas_ativas and not e.get("ativo", True):
            continue
        out.append(_enriquecer_empresa(e, cat))
    return out


def _enriquecer_empresa(raw: dict[str, Any], cat: dict[str, Any] | None = None) -> dict[str, Any]:
    cat = cat or carregar_catalogo()
    eid = str(raw.get("id") or "").strip()
    cnpj = _digitos(str(raw.get("cnpj") or ""))
    # Defaults operacionais dos dois CNPJs se o JSON vier sem dígitos
    if not cnpj and eid == "esmaltes_impala":
        cnpj = _digitos(ESMALTES_CNPJ)
    if not cnpj and eid == "masterprint":
        cnpj = _digitos(DEMAIS_PRODUTOS_CNPJ)
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
                "codigo_norm": _norm_cnae(codigo),
                "descricao": str(c.get("descricao") or "").strip(),
                "principal": bool(c.get("principal")),
            }
        )
    mk = raw.get("marketplaces") if isinstance(raw.get("marketplaces"), dict) else {}
    foco = _norm_marketplace(
        mk.get("foco_principal")
        or cat.get("foco_marketplace_padrao")
        or MARKETPLACE_FOCO_PRINCIPAL
        or "mercadolivre"
    )
    ativos = [_norm_marketplace(x) for x in (mk.get("ativos") or ["mercadolivre"])]
    ativos = [a for a in ativos if a]
    if foco and foco not in ativos:
        ativos = [foco, *ativos]
    secundarios = [_norm_marketplace(x) for x in (mk.get("secundarios") or [])]
    ml = raw.get("ml") if isinstance(raw.get("ml"), dict) else {}

    return {
        "id": str(raw.get("id") or "").strip(),
        "ativo": bool(raw.get("ativo", True)),
        "nome_fantasia": str(raw.get("nome_fantasia") or "").strip(),
        "razao_social": str(raw.get("razao_social") or "").strip(),
        "cnpj": cnpj,
        "cnpj_formatado": formatar_cnpj(cnpj),
        "cnaes": cnaes,
        "cnae_principal": next((c for c in cnaes if c.get("principal")), cnaes[0] if cnaes else None),
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
        "telegram_gestor_chat_id": str(raw.get("telegram_gestor_chat_id") or "").strip(),
        "ramos": [str(r).strip() for r in (raw.get("ramos") or []) if str(r).strip()],
        "agentes_prioritarios": [
            str(a).strip() for a in (raw.get("agentes_prioritarios") or []) if str(a).strip()
        ],
        "notas": raw.get("notas") or "",
        "prioriza_mercadolivre": foco == "mercadolivre",
    }


def empresa_por_id(empresa_id: str) -> dict[str, Any] | None:
    eid = str(empresa_id or "").strip()
    if not eid:
        return None
    for e in listar_empresas(apenas_ativas=False):
        if e.get("id") == eid:
            return e
    return None


def empresa_por_cnpj(cnpj: str) -> dict[str, Any] | None:
    alvo = _digitos(cnpj)
    if len(alvo) != 14:
        return None
    for e in listar_empresas(apenas_ativas=False):
        if e.get("cnpj") == alvo:
            return e
    return None


def empresas_por_cnae(codigo: str) -> list[dict[str, Any]]:
    alvo = _norm_cnae(codigo)
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


def empresa_ativa() -> dict[str, Any] | None:
    """
    Resolve empresa ativa:
      1) EMPRESA_ATIVA_CNPJ
      2) EMPRESA_ATIVA_ID / catalogo.empresa_ativa_id
      3) primeira empresa ativa do catálogo
    Não sobrescreve ML_SELLER_ID global — apenas reporta o perfil.
    """
    cat = carregar_catalogo()
    if EMPRESA_ATIVA_CNPJ:
        achada = empresa_por_cnpj(EMPRESA_ATIVA_CNPJ)
        if achada:
            return _aplicar_overrides_env(achada)
    eid = str(EMPRESA_ATIVA_ID or cat.get("empresa_ativa_id") or "").strip()
    if eid:
        achada = empresa_por_id(eid)
        if achada:
            return _aplicar_overrides_env(achada)
    empresas = listar_empresas(apenas_ativas=True)
    if not empresas:
        return None
    return _aplicar_overrides_env(empresas[0])


def _aplicar_overrides_env(empresa: dict[str, Any]) -> dict[str, Any]:
    """Mantém configs atuais: se ML_SELLER_ID / Telegram global existirem e a empresa for a ativa de esmaltes, espelha."""
    out = dict(empresa)
    ml = dict(out.get("ml") or {})
    eid = out.get("id")
    if eid == "esmaltes_impala":
        if ML_SELLER_ID and not ml.get("seller_id"):
            ml["seller_id"] = ML_SELLER_ID
        if TELEGRAM_GESTOR_CHAT_ID and not out.get("telegram_gestor_chat_id"):
            out["telegram_gestor_chat_id"] = TELEGRAM_GESTOR_CHAT_ID
        cnpj_env = _digitos(EMPRESA_ATIVA_CNPJ or ESMALTES_CNPJ)
        if cnpj_env and (not out.get("cnpj") or _digitos(ESMALTES_CNPJ) == cnpj_env):
            # Preferência: ESMALTES_CNPJ operacional; EMPRESA_ATIVA_CNPJ se for o de esmaltes
            prefer = _digitos(ESMALTES_CNPJ) or cnpj_env
            if prefer:
                out["cnpj"] = prefer
                out["cnpj_formatado"] = formatar_cnpj(prefer)
    elif eid == "masterprint":
        prefer = _digitos(
            getattr(_cfg, "MASTERPRINT_CNPJ", "") or DEMAIS_PRODUTOS_CNPJ
        )
        if prefer and not out.get("cnpj"):
            out["cnpj"] = prefer
            out["cnpj_formatado"] = formatar_cnpj(prefer)
        elif prefer:
            # Garante o CNPJ operacional dos demais produtos
            out["cnpj"] = prefer
            out["cnpj_formatado"] = formatar_cnpj(prefer)
    out["ml"] = ml
    return out


def empresa_para_proposito(proposito: str | None) -> dict[str, Any] | None:
    """Roteia análise Claude/agente para o CNPJ certo conforme o propósito."""
    p = str(proposito or "").strip().lower()
    demais = (
        "masterprint",
        "filamento",
        "escritorio",
        "petg",
        "demais",
        "apagador",
        "pincel",
    )
    esmaltes = (
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
    )
    emp = None
    if any(k in p for k in demais):
        emp = empresa_por_id("masterprint")
    elif any(k in p for k in esmaltes):
        emp = empresa_por_id("esmaltes_impala")
    else:
        return empresa_ativa()
    return _aplicar_overrides_env(emp) if emp else None


def mapa_dois_cnpjs() -> dict[str, Any]:
    """Resumo fixo dos dois CNPJs para prompts Claude / Telegram."""
    esm = empresa_por_id("esmaltes_impala") or {}
    dem = empresa_por_id("masterprint") or {}
    dono = situacao_dono_produtos()
    return {
        "esmaltes": {
            "empresa_id": "esmaltes_impala",
            "cnpj": esm.get("cnpj") or _digitos(ESMALTES_CNPJ),
            "cnpj_formatado": esm.get("cnpj_formatado") or formatar_cnpj(ESMALTES_CNPJ),
            "nome": esm.get("nome_fantasia") or "Impala / esmaltes",
        },
        "demais_produtos": {
            "empresa_id": "masterprint",
            "cnpj": dem.get("cnpj") or _digitos(DEMAIS_PRODUTOS_CNPJ),
            "cnpj_formatado": dem.get("cnpj_formatado")
            or formatar_cnpj(DEMAIS_PRODUTOS_CNPJ),
            "nome": dem.get("nome_fantasia") or "Masterprint / demais produtos",
        },
        "dono_produtos": dono,
    }


def cnpj_dono_produtos_efetivo() -> str:
    """
    CNPJ dono dos dados de produtos agora.
    Default: 52668583000127. Com CNPJ_DONO_PRODUTOS_USAR_ALVO=1 → alvo (238…).
    """
    cat = carregar_catalogo()
    bloco = cat.get("dono_produtos") if isinstance(cat.get("dono_produtos"), dict) else {}
    usar_alvo = CNPJ_DONO_PRODUTOS_USAR_ALVO or bool(bloco.get("usar_alvo"))
    if usar_alvo:
        return _digitos(
            CNPJ_DONO_PRODUTOS_ALVO
            or bloco.get("cnpj_alvo")
            or DEMAIS_PRODUTOS_CNPJ
        )
    return _digitos(
        CNPJ_DONO_PRODUTOS
        or bloco.get("cnpj_atual")
        or ESMALTES_CNPJ
    )


def situacao_dono_produtos() -> dict[str, Any]:
    """Estado da migração: produtos hoje no CNPJ atual, alvo pronto para troca."""
    cat = carregar_catalogo()
    bloco = cat.get("dono_produtos") if isinstance(cat.get("dono_produtos"), dict) else {}
    atual = _digitos(bloco.get("cnpj_atual") or CNPJ_DONO_PRODUTOS or ESMALTES_CNPJ)
    alvo = _digitos(
        bloco.get("cnpj_alvo") or CNPJ_DONO_PRODUTOS_ALVO or DEMAIS_PRODUTOS_CNPJ
    )
    efetivo = cnpj_dono_produtos_efetivo()
    usando_alvo = efetivo == alvo and alvo != ""
    emp = empresa_por_cnpj(efetivo) or (
        empresa_por_id("masterprint") if usando_alvo else empresa_por_id("esmaltes_impala")
    )
    return {
        "cnpj_efetivo": efetivo,
        "cnpj_formatado": formatar_cnpj(efetivo),
        "cnpj_atual_configurado": atual,
        "cnpj_alvo": alvo,
        "usando_alvo": usando_alvo,
        "migracao_pendente": (not usando_alvo) and atual != alvo,
        "empresa_id": (emp or {}).get("id"),
        "nome_fantasia": (emp or {}).get("nome_fantasia"),
        "como_trocar": (
            "Defina CNPJ_DONO_PRODUTOS_USAR_ALVO=1 (ou dono_produtos.usar_alvo=true "
            "em catalogo/empresas_cnae_cnpj.json) para passar os dados de produtos "
            f"de {formatar_cnpj(atual)} para {formatar_cnpj(alvo)}."
        ),
        "notas": bloco.get("notas") or "",
    }


def empresa_dono_produtos() -> dict[str, Any] | None:
    """Empresa dona dos catálogos de produtos no momento."""
    sit = situacao_dono_produtos()
    emp = empresa_por_cnpj(sit["cnpj_efetivo"])
    if emp:
        return _aplicar_overrides_env(emp)
    return empresa_por_id(sit.get("empresa_id") or "esmaltes_impala")


def marketplace_foco(empresa: dict[str, Any] | None = None) -> str:
    emp = empresa or empresa_ativa()
    if emp:
        return str((emp.get("marketplaces") or {}).get("foco_principal") or "mercadolivre")
    return _norm_marketplace(MARKETPLACE_FOCO_PRINCIPAL or "mercadolivre") or "mercadolivre"


def prioriza_mercadolivre(empresa: dict[str, Any] | None = None) -> bool:
    return marketplace_foco(empresa) == "mercadolivre"


def contexto_analise(
    *,
    ramo: str | None = None,
    empresa_id: str | None = None,
) -> dict[str, Any]:
    """
    Bloco pronto para agentes/Claude: empresa, CNAEs, CNPJ e foco ML.
    Configs atuais permanecem; este contexto só orienta a análise.
    """
    emp = None
    if empresa_id:
        emp = empresa_por_id(empresa_id)
    if not emp and ramo:
        emp = empresa_por_ramo(ramo)
    if not emp:
        emp = empresa_ativa()

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
