"""
integracoes/importacao/portos_brasil.py
Catálogo de portos e aeroportos do Brasil com custos estimados
para importação referenciada em Alibaba (FOB China).
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from core.atomic_io import ler_json
from core.config import ROOT

logger = logging.getLogger("portos_brasil")

TipoModal = Literal["aereo", "maritimo", "todos"]

_CATALOGO_DEFAULT = "catalogo/portos_aeroportos_brasil.json"
_ICMS_UF = {
    "AC": 19.0, "AL": 19.0, "AP": 18.0, "AM": 18.0, "BA": 20.5, "CE": 18.0,
    "DF": 18.0, "ES": 17.0, "GO": 19.0, "MA": 18.0, "MT": 17.0, "MS": 17.0,
    "MG": 18.0, "PA": 17.0, "PB": 18.0, "PR": 18.0, "PE": 18.0, "PI": 18.0,
    "RJ": 20.0, "RN": 18.0, "RS": 17.0, "RO": 17.5, "RR": 17.0, "SC": 17.0,
    "SP": 18.0, "SE": 18.0, "TO": 18.0,
}


def _catalogo_path() -> str:
    from core import config as cfg

    return str(
        getattr(cfg, "IMPORTACAO_PORTOS_BRASIL_CATALOGO", "")
        or _CATALOGO_DEFAULT
    )


def carregar_catalogo_portos() -> dict[str, Any]:
    data = ler_json(ROOT / _catalogo_path(), default={})
    return data if isinstance(data, dict) else {}


def listar_gateways(
    *,
    modal: TipoModal = "todos",
    apenas_ativos: bool = True,
    uf: str | None = None,
) -> list[dict[str, Any]]:
    """Lista aeroportos e/ou portos com estrutura de custo."""
    cat = carregar_catalogo_portos()
    itens: list[dict[str, Any]] = []
    if modal in ("aereo", "todos"):
        itens.extend(cat.get("aeroportos") or [])
    if modal in ("maritimo", "todos"):
        itens.extend(cat.get("portos") or [])

    out: list[dict[str, Any]] = []
    uf_f = (uf or "").strip().upper()
    for g in itens:
        if not isinstance(g, dict):
            continue
        if apenas_ativos and not g.get("ativo", True):
            continue
        if uf_f and str(g.get("uf") or "").upper() != uf_f:
            continue
        out.append(dict(g))
    out.sort(key=lambda x: (-float(x.get("atratividade") or 0), str(x.get("codigo") or "")))
    return out


def gateway_por_codigo(codigo: str) -> dict[str, Any] | None:
    cod = str(codigo or "").strip().upper()
    if not cod:
        return None
    for g in listar_gateways(modal="todos", apenas_ativos=False):
        if str(g.get("codigo") or "").upper() == cod:
            return g
    return None


def distancia_km_para_cep(codigo_gateway: str, cep: str | None = None) -> float:
    """Distância aproximada gateway → CEP destino (tabela do catálogo)."""
    from integracoes.importacao.operacao_destino import normalizar_cep

    cat = carregar_catalogo_portos()
    cep_n = normalizar_cep(cep or cat.get("destino_padrao_cep") or "13467-694")
    tabela = cat.get("distancias_km_aproximadas") or {}
    # tenta CEP exato; senão usa o padrão do catálogo
    bloco = tabela.get(cep_n) or tabela.get(cat.get("destino_padrao_cep") or "13467-694") or {}
    try:
        return float(bloco.get(str(codigo_gateway).upper()) or 500.0)
    except (TypeError, ValueError):
        return 500.0


def icms_gateway(gateway: dict[str, Any], uf_destino: str | None = None) -> float:
    if gateway.get("icms_uf_pct") is not None:
        try:
            return float(gateway["icms_uf_pct"])
        except (TypeError, ValueError):
            pass
    uf = (uf_destino or gateway.get("uf") or "SP").upper()
    return float(_ICMS_UF.get(uf, 18.0))


def resumo_estrutura_gateway(gateway: dict[str, Any]) -> dict[str, Any]:
    custos = gateway.get("custos_locais_brl") or {}
    locais = sum(float(custos.get(k) or 0) for k in (
        "armazenagem", "desembaraco", "thc_manuseio", "siscomex", "outros"
    ))
    return {
        "codigo": gateway.get("codigo"),
        "nome": gateway.get("nome"),
        "cidade": gateway.get("cidade"),
        "uf": gateway.get("uf"),
        "tipo": gateway.get("tipo"),
        "atratividade_catalogo": gateway.get("atratividade"),
        "frete_internacional_usd_kg": gateway.get("frete_internacional_usd_kg"),
        "custos_locais_brl_total": round(locais, 2),
        "custos_locais_brl": custos,
        "frete_interno_brl_por_km": gateway.get("frete_interno_brl_por_km"),
        "notas": gateway.get("notas") or "",
    }
