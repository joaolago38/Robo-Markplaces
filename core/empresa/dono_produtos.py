"""
core/empresa/dono_produtos.py — Strategy: dono atual vs alvo dos catálogos.

Hoje: 52668583000127. Alvo: 23811261000197 (CNPJ_DONO_PRODUTOS_USAR_ALVO=1).
"""
from __future__ import annotations

from typing import Any

from core.empresa.catalogo import carregar_catalogo, empresa_por_cnpj, empresa_por_id
from core.empresa.cnpj_utils import digitos, formatar_cnpj
from core.empresa.flags import flag
from core.empresa.overrides import aplicar_overrides_env


def cnpj_dono_produtos_efetivo() -> str:
    cat = carregar_catalogo()
    bloco = cat.get("dono_produtos") if isinstance(cat.get("dono_produtos"), dict) else {}
    usar_alvo = bool(flag("CNPJ_DONO_PRODUTOS_USAR_ALVO", False)) or bool(bloco.get("usar_alvo"))
    if usar_alvo:
        return digitos(
            str(
                flag("CNPJ_DONO_PRODUTOS_ALVO", "")
                or bloco.get("cnpj_alvo")
                or flag("DEMAIS_PRODUTOS_CNPJ", "23811261000197")
            )
        )
    return digitos(
        str(
            flag("CNPJ_DONO_PRODUTOS", "")
            or bloco.get("cnpj_atual")
            or flag("ESMALTES_CNPJ", "52668583000127")
        )
    )


def situacao_dono_produtos() -> dict[str, Any]:
    cat = carregar_catalogo()
    bloco = cat.get("dono_produtos") if isinstance(cat.get("dono_produtos"), dict) else {}
    atual = digitos(
        str(
            bloco.get("cnpj_atual")
            or flag("CNPJ_DONO_PRODUTOS", "")
            or flag("ESMALTES_CNPJ", "52668583000127")
        )
    )
    alvo = digitos(
        str(
            bloco.get("cnpj_alvo")
            or flag("CNPJ_DONO_PRODUTOS_ALVO", "")
            or flag("DEMAIS_PRODUTOS_CNPJ", "23811261000197")
        )
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
    sit = situacao_dono_produtos()
    emp = empresa_por_cnpj(sit["cnpj_efetivo"])
    if emp:
        return aplicar_overrides_env(emp)
    return empresa_por_id(sit.get("empresa_id") or "esmaltes_impala")
