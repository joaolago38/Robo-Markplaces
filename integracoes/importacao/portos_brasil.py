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

TipoModal = Literal["aereo", "maritimo", "terrestre", "todos"]

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
    """
    ICMS para o cálculo.
    Se uf_destino informado, usa a alíquota do destino (comparação justa entre portos).
    Senão, cai no icms_uf_pct do gateway ou UF do porto.
    """
    if uf_destino:
        return float(_ICMS_UF.get(str(uf_destino).upper(), 18.0))
    if gateway.get("icms_uf_pct") is not None:
        try:
            return float(gateway["icms_uf_pct"])
        except (TypeError, ValueError):
            pass
    uf = (gateway.get("uf") or "SP").upper()
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


def cobertura_costa_brasil() -> dict[str, Any]:
    """
    % dos hubs de referência da costa brasileira presentes e ativos no catálogo.
    """
    cat = carregar_catalogo_portos()
    ref = (cat.get("cobertura_costa_referencia") or {}).get("codigos") or []
    ref_set = {str(c).upper() for c in ref}
    ativos = {
        str(g.get("codigo") or "").upper()
        for g in listar_gateways(modal="maritimo", apenas_ativos=True)
    }
    cobertos = sorted(ref_set & ativos)
    faltando = sorted(ref_set - ativos)
    total_ref = len(ref_set) or 1
    pct = round(100.0 * len(cobertos) / total_ref, 1)
    return {
        "ok": True,
        "referencia_total": len(ref_set),
        "cobertos": cobertos,
        "faltando": faltando,
        "cobertura_pct": pct,
        "portos_maritimos_ativos": len(ativos),
        "ufs_costa": sorted(
            {
                str(g.get("uf") or "")
                for g in listar_gateways(modal="maritimo", apenas_ativos=True)
                if g.get("uf") and g.get("codigo") in cobertos
            }
        ),
    }


def endereco_comercial_paraguai() -> dict[str, Any]:
    """Endereço comercial PY (default Ciudad del Este) — sobrescritível por env."""
    from core import config as cfg

    cat = carregar_catalogo_portos()
    py = cat.get("paraguai") if isinstance(cat.get("paraguai"), dict) else {}
    base = dict(py.get("endereco_comercial_padrao") or {})

    if getattr(cfg, "IMPORTACAO_PY_ENDERECO", ""):
        base["endereco"] = cfg.IMPORTACAO_PY_ENDERECO
    if getattr(cfg, "IMPORTACAO_PY_CIDADE", ""):
        base["cidade"] = cfg.IMPORTACAO_PY_CIDADE
    if getattr(cfg, "IMPORTACAO_PY_DEPARTAMENTO", ""):
        base["departamento"] = cfg.IMPORTACAO_PY_DEPARTAMENTO
    if getattr(cfg, "IMPORTACAO_PY_CODIGO_POSTAL", ""):
        base["codigo_postal"] = cfg.IMPORTACAO_PY_CODIGO_POSTAL

    return {
        "ok": bool(py.get("ativo", True) and base),
        "ativo": bool(py.get("ativo", True)),
        "endereco": base,
        "alternativos": list(py.get("enderecos_alternativos") or []),
        "via_env": bool(getattr(cfg, "IMPORTACAO_PY_ENDERECO", "") or getattr(cfg, "IMPORTACAO_PY_CIDADE", "")),
    }


def corredores_terrestres_py_br(*, cep_destino: str | None = None) -> list[dict[str, Any]]:
    from integracoes.importacao.operacao_destino import normalizar_cep

    cat = carregar_catalogo_portos()
    py = cat.get("paraguai") if isinstance(cat.get("paraguai"), dict) else {}
    cep = normalizar_cep(cep_destino or cat.get("destino_padrao_cep") or "13467-694")
    out = []
    for c in py.get("corredores_terrestres") or []:
        if not isinstance(c, dict) or not c.get("ativo", True):
            continue
        item = dict(c)
        # Se o corredor tem CEP padrão diferente e o usuário pediu outro, ajusta km via tabela se houver
        dest_padrao = normalizar_cep(str(item.get("destino_cep_padrao") or ""))
        if cep != dest_padrao:
            item["destino_cep"] = cep
            item["km_ajustado"] = True
        else:
            item["destino_cep"] = cep
            item["km_ajustado"] = False
        out.append(item)
    return out


def calcular_frete_terrestre_py_br(
    corredor: dict[str, Any],
    *,
    valor_carga_brl: float = 0.0,
    quantidade: int = 1,
) -> dict[str, Any]:
    """Custo terrestre PY → fronteira BR → CEP destino (estrutura no Brasil)."""
    km = float(corredor.get("km_total_aprox") or 0)
    if km <= 0:
        km = float(corredor.get("km_origem_fronteira") or 0) + float(
            corredor.get("km_fronteira_destino") or 0
        )
    por_km = float(corredor.get("custo_terrestre_brl_por_km") or 4.2)
    fixo = float(corredor.get("custo_fixo_fronteira_brl") or 0)
    pedagios = float(corredor.get("pedagios_estim_brl") or 0)
    seguro_pct = float(corredor.get("seguro_carga_pct") or 0)
    frete = km * por_km
    seguro = valor_carga_brl * (seguro_pct / 100.0)
    total = frete + fixo + pedagios + seguro
    qty = max(1, int(quantidade))
    return {
        "ok": True,
        "modal": "terrestre",
        "corredor_id": corredor.get("id"),
        "origem": corredor.get("origem"),
        "fronteira_br": corredor.get("fronteira_br"),
        "uf_entrada": corredor.get("uf_entrada"),
        "destino_cep": corredor.get("destino_cep"),
        "km_total": round(km, 1),
        "frete_km_brl": round(frete, 2),
        "fixo_fronteira_brl": round(fixo, 2),
        "pedagios_brl": round(pedagios, 2),
        "seguro_brl": round(seguro, 2),
        "custo_total_brl": round(total, 2),
        "custo_unitario_brl": round(total / qty, 2),
        "dias_transito_estim": corredor.get("dias_transito_estim"),
    }
