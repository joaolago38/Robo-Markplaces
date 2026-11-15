"""core/empresa/overrides.py — aplica env atual sem substituir configs (SRP)."""
from __future__ import annotations

import os
from typing import Any

import core.config as _cfg
from core.empresa.cnpj_utils import digitos, formatar_cnpj
from core.empresa.flags import flag


def _segredo(*nomes: str) -> str:
    """Env vivo primeiro; config importada se o processo já nasceu com o valor."""
    for nome in nomes:
        vivo = os.getenv(nome, "").strip()
        if vivo:
            return vivo
    for nome in nomes:
        fixo = str(getattr(_cfg, nome, "") or "").strip()
        if fixo:
            return fixo
    return ""


def _ids_impala(bloco: str, chave: str, *envs: str) -> set[str]:
    """IDs da Impala que a Masterprint não pode reutilizar."""
    ids = {v for v in (_segredo(nome) for nome in envs) if v}
    try:
        from core.empresa.catalogo import empresa_por_id

        emp = empresa_por_id("esmaltes_impala") or {}
        cat = str((emp.get(bloco) or {}).get(chave) or "").strip()
        if cat:
            ids.add(cat)
    except Exception:
        pass
    return ids


def aplicar_overrides_env(empresa: dict[str, Any]) -> dict[str, Any]:
    """Espelha ML_SELLER_ID / Telegram / CNPJs operacionais quando couber."""
    out = dict(empresa)
    ml = dict(out.get("ml") or {})
    eid = out.get("id")
    if eid == "esmaltes_impala":
        ml_seller = flag("ML_SELLER_ID", "")
        tg = flag("TELEGRAM_GESTOR_CHAT_ID", "")
        if ml_seller:
            ml["seller_id"] = ml_seller
        if tg and not out.get("telegram_gestor_chat_id"):
            out["telegram_gestor_chat_id"] = tg
        esmaltes = digitos(str(flag("ESMALTES_CNPJ", "52668583000127")))
        ativa = digitos(str(flag("EMPRESA_ATIVA_CNPJ", "") or ""))
        cnpj_env = ativa or esmaltes
        if cnpj_env and (not out.get("cnpj") or esmaltes == cnpj_env):
            prefer = esmaltes or cnpj_env
            if prefer:
                out["cnpj"] = prefer
                out["cnpj_formatado"] = formatar_cnpj(prefer)
    elif eid == "masterprint":
        prefer = digitos(
            str(getattr(_cfg, "MASTERPRINT_CNPJ", "") or flag("DEMAIS_PRODUTOS_CNPJ", ""))
        )
        if prefer:
            out["cnpj"] = prefer
            out["cnpj_formatado"] = formatar_cnpj(prefer)
        mp_seller = _segredo("MASTERPRINT_ML_SELLER_ID", "ML_SELLER_ID_MASTERPRINT")
        mp_nick = _segredo("MASTERPRINT_ML_NICKNAME")
        proibidos = _ids_impala("ml", "seller_id", "ML_SELLER_ID")
        if mp_seller and not ml.get("seller_id") and mp_seller not in proibidos:
            ml["seller_id"] = mp_seller
        if mp_nick and not ml.get("nickname"):
            ml["nickname"] = mp_nick
    out["ml"] = ml
    shopee = dict(out.get("shopee") or {})
    magalu = dict(out.get("magalu") or {})
    amazon = dict(out.get("amazon") or {})
    if eid == "esmaltes_impala":
        shop = flag("SHOPEE_SHOP_ID", "")
        if shop and not shopee.get("shop_id"):
            shopee["shop_id"] = shop
        mag_seller = str(getattr(_cfg, "MAGALU_SELLER_ID", "") or flag("MAGALU_SELLER_ID", "")).strip()
        if mag_seller and not magalu.get("seller_id"):
            magalu["seller_id"] = mag_seller
        amz = str(getattr(_cfg, "AMAZON_SELLER_ID", "") or flag("AMAZON_SELLER_ID", "")).strip()
        if amz and not amazon.get("seller_id"):
            amazon["seller_id"] = amz
    elif eid == "masterprint":
        shop = _segredo("MASTERPRINT_SHOPEE_SHOP_ID")
        if shop and not shopee.get("shop_id") and shop not in _ids_impala("shopee", "shop_id", "SHOPEE_SHOP_ID"):
            shopee["shop_id"] = shop
        mag_seller = _segredo("MASTERPRINT_MAGALU_SELLER_ID")
        if (
            mag_seller
            and not magalu.get("seller_id")
            and mag_seller not in _ids_impala("magalu", "seller_id", "MAGALU_SELLER_ID")
        ):
            magalu["seller_id"] = mag_seller
        amz = _segredo("MASTERPRINT_AMAZON_SELLER_ID")
        if amz and not amazon.get("seller_id") and amz not in _ids_impala("amazon", "seller_id", "AMAZON_SELLER_ID"):
            amazon["seller_id"] = amz
    out["shopee"] = shopee
    out["magalu"] = magalu
    out["amazon"] = amazon
    return out
