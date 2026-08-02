"""core/empresa/cnpj_utils.py — utilitários de CNPJ (SRP)."""
from __future__ import annotations

import re

_RE_DIG = re.compile(r"\D+")


def digitos(valor: str) -> str:
    return _RE_DIG.sub("", str(valor or ""))


def formatar_cnpj(cnpj: str) -> str:
    d = digitos(cnpj)
    if len(d) != 14:
        return d or ""
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def norm_cnae(codigo: str) -> str:
    return re.sub(r"[^0-9]", "", str(codigo or ""))
