"""
integracoes/importacao/operacao_destino.py
Operação de importação aérea referenciada a Viracopos (Campinas)
com destino CEP configurável (default 13467-694).

Prioridade: env (IMPORTACAO_DESTINO_CEP etc.) > catalogo JSON > fallback.
"""
from __future__ import annotations

import re
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT

_CEP_DEFAULT = "13467-694"
_AEROPORTO_DEFAULT = {
    "codigo": "VCP",
    "nome": "Viracopos",
    "cidade": "Campinas",
    "uf": "SP",
}
_DESTINO_DEFAULT = {
    "cep": _CEP_DEFAULT,
    "cidade": "Americana",
    "uf": "SP",
    "distancia_km_viracopos": 120.0,
}


def normalizar_cep(cep: str | None) -> str:
    """Mantém formato 00000-000 quando possível."""
    digitos = re.sub(r"\D", "", str(cep or ""))
    if len(digitos) != 8:
        return str(cep or "").strip() or _CEP_DEFAULT
    return f"{digitos[:5]}-{digitos[5:]}"


def _overlay_env(base: dict[str, Any]) -> dict[str, Any]:
    from core import config as cfg

    out = dict(base or {})
    aero = dict(out.get("aeroporto_desembaraco") or _AEROPORTO_DEFAULT)
    dest = dict(out.get("destino_entrega") or _DESTINO_DEFAULT)

    if getattr(cfg, "IMPORTACAO_AEROPORTO_CODIGO", ""):
        aero["codigo"] = cfg.IMPORTACAO_AEROPORTO_CODIGO
    if getattr(cfg, "IMPORTACAO_AEROPORTO_NOME", ""):
        aero["nome"] = cfg.IMPORTACAO_AEROPORTO_NOME
    if getattr(cfg, "IMPORTACAO_AEROPORTO_CIDADE", ""):
        aero["cidade"] = cfg.IMPORTACAO_AEROPORTO_CIDADE
    if getattr(cfg, "IMPORTACAO_AEROPORTO_UF", ""):
        aero["uf"] = cfg.IMPORTACAO_AEROPORTO_UF

    if getattr(cfg, "IMPORTACAO_DESTINO_CEP", ""):
        dest["cep"] = normalizar_cep(cfg.IMPORTACAO_DESTINO_CEP)
    else:
        dest["cep"] = normalizar_cep(dest.get("cep") or _CEP_DEFAULT)
    if getattr(cfg, "IMPORTACAO_DESTINO_CIDADE", ""):
        dest["cidade"] = cfg.IMPORTACAO_DESTINO_CIDADE
    if getattr(cfg, "IMPORTACAO_DESTINO_UF", ""):
        dest["uf"] = cfg.IMPORTACAO_DESTINO_UF
    km_env = getattr(cfg, "IMPORTACAO_DESTINO_KM_VIRACOPOS", "")
    if km_env:
        try:
            dest["distancia_km_viracopos"] = float(km_env)
        except (TypeError, ValueError):
            pass

    out["aeroporto_desembaraco"] = aero
    out["destino_entrega"] = dest
    out["cep_origem_config"] = bool(getattr(cfg, "IMPORTACAO_DESTINO_CEP", ""))
    return out


def carregar_operacao_destino(*, catalogo_rel: str | None = None) -> dict[str, Any]:
    """
    Carrega operação fixa + overlay de env.
    Default: VCP Campinas → CEP 13467-694 (Americana/SP).
    """
    from core import config as cfg

    path = catalogo_rel or getattr(
        cfg, "IMPORTACAO_OPERACAO_FIXA_CATALOGO", "catalogo/importacao_operacao_fixa.json"
    )
    base = ler_json(ROOT / path, default={})
    if not isinstance(base, dict):
        base = {}
    if not base.get("aeroporto_desembaraco"):
        base["aeroporto_desembaraco"] = dict(_AEROPORTO_DEFAULT)
    if not base.get("destino_entrega"):
        base["destino_entrega"] = dict(_DESTINO_DEFAULT)
    return _overlay_env(base)


def resumo_destino(operacao: dict[str, Any] | None = None) -> dict[str, Any]:
    op = operacao or carregar_operacao_destino()
    aero = op.get("aeroporto_desembaraco") or {}
    dest = op.get("destino_entrega") or {}
    codigo = str(aero.get("codigo") or "VCP")
    nome = str(aero.get("nome") or "Viracopos")
    return {
        "aeroporto_codigo": codigo,
        "aeroporto_nome": nome,
        "aeroporto_cidade": aero.get("cidade") or "Campinas",
        "aeroporto_label": f"{codigo} — {nome}",
        "destino_cep": normalizar_cep(dest.get("cep")),
        "destino_cidade": dest.get("cidade") or "Americana",
        "destino_uf": str(dest.get("uf") or "SP").upper(),
        "distancia_km": float(dest.get("distancia_km_viracopos") or 120),
        "cep_via_env": bool(op.get("cep_origem_config")),
    }
