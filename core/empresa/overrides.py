"""core/empresa/overrides.py — aplica env atual sem substituir configs (SRP)."""
from __future__ import annotations

from typing import Any

import core.config as _cfg
from core.empresa.cnpj_utils import digitos, formatar_cnpj
from core.empresa.flags import flag


def aplicar_overrides_env(empresa: dict[str, Any]) -> dict[str, Any]:
    """Espelha ML_SELLER_ID / Telegram / CNPJs operacionais quando couber."""
    out = dict(empresa)
    ml = dict(out.get("ml") or {})
    eid = out.get("id")
    if eid == "esmaltes_impala":
        ml_seller = flag("ML_SELLER_ID", "")
        tg = flag("TELEGRAM_GESTOR_CHAT_ID", "")
        if ml_seller and not ml.get("seller_id"):
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
    out["ml"] = ml
    return out
