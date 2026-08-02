"""
integracoes/importacao/rotas_regionais_china.py
Importação China → Brasil (marítimo):

- Sudeste e proximidades → preferir Santos (BRSSZ)
- Nordeste → portos do NE (Suape, Pecém, Salvador, Fortaleza, …)
- Sempre comparar tributação (ICMS/impostos) com portos do Sul
  (Paranaguá, Itajaí, Navegantes, Rio Grande, Imbituba, Itapoá)
"""
from __future__ import annotations

from typing import Any

from integracoes.importacao.portos_brasil import gateway_por_codigo, icms_gateway, listar_gateways

# UFs por macrorregião
_SUDESTE = frozenset({"SP", "RJ", "MG", "ES"})
_NORDESTE = frozenset({"BA", "PE", "CE", "RN", "PB", "AL", "SE", "MA", "PI"})
_SUL = frozenset({"PR", "SC", "RS"})
_NORTE = frozenset({"AM", "PA", "AP", "RR", "RO", "AC", "TO"})
_CENTRO = frozenset({"DF", "GO", "MT", "MS"})

# Preferências marítimas China → BR
PORTOS_SUDESTE = ("BRSSZ", "BRSSO", "BRRIO", "BRVIX")  # Santos 1º
PORTOS_NORDESTE = ("BRSUA", "BRPEC", "BRSSB", "BRFOR", "BRARB", "BRNAT", "BRCDO", "BRIOA", "BRIOS")
PORTOS_SUL_COMPARATIVO = ("BRPNG", "BRITJ", "BRNVT", "BRITP", "BRIGI", "BRRIG")  # tributação Sul
PORTOS_NORTE = ("BRVDC", "BRSTM", "BRMAO")


def regiao_por_uf(uf: str | None) -> str:
    u = (uf or "SP").strip().upper()
    if u in _SUDESTE:
        return "sudeste"
    if u in _NORDESTE:
        return "nordeste"
    if u in _SUL:
        return "sul"
    if u in _NORTE:
        return "norte"
    if u in _CENTRO:
        return "centro_oeste"
    return "sudeste"


def portos_preferidos_china(uf_destino: str | None) -> dict[str, Any]:
    """
    Define hub principal e lista preferida conforme região do destino.
    Sudeste → Santos; Nordeste → hubs NE; demais → mais próximo da lógica regional.
    """
    regiao = regiao_por_uf(uf_destino)
    if regiao == "sudeste" or regiao == "centro_oeste":
        # Centro-Oeste costuma entrar por Santos (Sudeste)
        preferidos = list(PORTOS_SUDESTE)
        principal = "BRSSZ"
        motivo = "Destino Sudeste/Centro-Oeste → Santos (BRSSZ) como hub China"
    elif regiao == "nordeste":
        preferidos = list(PORTOS_NORDESTE)
        principal = "BRSUA"
        motivo = "Destino Nordeste → Suape/Pecém/Salvador (portos NE)"
    elif regiao == "sul":
        preferidos = list(PORTOS_SUL_COMPARATIVO)
        principal = "BRPNG"
        motivo = "Destino Sul → Paranaguá/Itajaí como hub; Santos fica comparativo"
    else:
        preferidos = list(PORTOS_NORTE) + ["BRSSZ"]
        principal = "BRVDC"
        motivo = "Destino Norte → Vila do Conde/Santana; Santos como alternativa SE"

    sul_comp = list(PORTOS_SUL_COMPARATIVO)
    # Garante que o principal está na lista e existe no catálogo
    ativos = {str(g.get("codigo") or "").upper() for g in listar_gateways(modal="maritimo")}
    preferidos = [c for c in preferidos if c in ativos] or ["BRSSZ"]
    sul_comp = [c for c in sul_comp if c in ativos]
    if principal not in preferidos and principal in ativos:
        preferidos.insert(0, principal)
    if principal not in ativos:
        principal = preferidos[0]

    return {
        "regiao": regiao,
        "uf_destino": (uf_destino or "SP").upper(),
        "porto_principal": principal,
        "portos_preferidos": preferidos,
        "portos_sul_comparativo_tributacao": sul_comp,
        "motivo": motivo,
        "icms_uf_destino_pct": icms_gateway({"uf": uf_destino}, uf_destino),
    }


def codigos_para_avaliacao_china(
    uf_destino: str | None,
    *,
    incluir_sul_comparativo: bool = True,
) -> list[str]:
    """Códigos marítimos a avaliar: preferidos da região + Sul (tributação)."""
    pref = portos_preferidos_china(uf_destino)
    codigos: list[str] = []
    for c in pref["portos_preferidos"]:
        if c not in codigos:
            codigos.append(c)
    if incluir_sul_comparativo:
        for c in pref["portos_sul_comparativo_tributacao"]:
            if c not in codigos:
                codigos.append(c)
    # Santos sempre no radar SE/CO/comparativo nacional China
    if "BRSSZ" not in codigos and gateway_por_codigo("BRSSZ"):
        codigos.append("BRSSZ")
    return codigos


def comparar_tributacao_regional(
    cenarios: list[dict[str, Any]],
    *,
    uf_destino: str | None,
) -> dict[str, Any]:
    """
    Separa cenários do hub regional vs portos do Sul e compara impostos/ICMS.
    """
    pref = portos_preferidos_china(uf_destino)
    set_pref = set(pref["portos_preferidos"])
    set_sul = set(pref["portos_sul_comparativo_tributacao"])
    principal = pref["porto_principal"]

    def _pick(codigo: str) -> dict[str, Any] | None:
        for c in cenarios:
            if not c.get("ok"):
                continue
            g = c.get("gateway") or {}
            if str(g.get("codigo") or "").upper() == codigo and c.get("modal") == "maritimo":
                return c
        return None

    def _resumo_trib(c: dict[str, Any] | None) -> dict[str, Any] | None:
        if not c:
            return None
        landed = c.get("landed") or {}
        g = c.get("gateway") or {}
        return {
            "codigo": g.get("codigo"),
            "nome": g.get("nome"),
            "uf_porto": g.get("uf"),
            "custo_unitario_brl": c.get("custo_unitario_brl"),
            "impostos_total_brl": c.get("impostos_total_brl") or landed.get("impostos_total_brl"),
            "icms_brl": landed.get("icms_brl"),
            "icms_pct": landed.get("icms_pct"),
            "cif_brl": c.get("cif_brl") or landed.get("cif_brl"),
            "assertividade_pct": c.get("assertividade_pct"),
        }

    hub = _pick(principal)
    # Melhor preferido da região
    prefs = [
        c for c in cenarios
        if c.get("ok")
        and c.get("modal") == "maritimo"
        and str((c.get("gateway") or {}).get("codigo") or "").upper() in set_pref
    ]
    prefs.sort(key=lambda x: float(x.get("custo_unitario_brl") or 1e9))
    melhor_regiao = prefs[0] if prefs else hub

    sul = [
        c for c in cenarios
        if c.get("ok")
        and c.get("modal") == "maritimo"
        and str((c.get("gateway") or {}).get("codigo") or "").upper() in set_sul
    ]
    sul.sort(key=lambda x: float(x.get("custo_unitario_brl") or 1e9))
    melhor_sul = sul[0] if sul else None

    delta_custo = None
    delta_impostos = None
    r_reg = _resumo_trib(melhor_regiao)
    r_sul = _resumo_trib(melhor_sul)
    if r_reg and r_sul:
        delta_custo = round(
            float(r_sul["custo_unitario_brl"] or 0) - float(r_reg["custo_unitario_brl"] or 0), 2
        )
        delta_impostos = round(
            float(r_sul.get("impostos_total_brl") or 0) - float(r_reg.get("impostos_total_brl") or 0),
            2,
        )

    veredito = "usar_hub_regional"
    if r_reg and r_sul and delta_custo is not None:
        if delta_custo < -1.0:
            veredito = "sul_mais_barato_avaliar_tributacao"
        elif abs(delta_custo) <= 1.0:
            veredito = "empate_operacional_preferir_hub_regional"
        else:
            veredito = "hub_regional_mais_barato"

    return {
        "ok": bool(r_reg or r_sul),
        "regiao": pref["regiao"],
        "uf_destino": pref["uf_destino"],
        "icms_uf_destino_pct": pref["icms_uf_destino_pct"],
        "motivo_rota": pref["motivo"],
        "hub_principal": _resumo_trib(hub) or r_reg,
        "melhor_regiao": r_reg,
        "melhor_sul_tributacao": r_sul,
        "ranking_sul": [_resumo_trib(c) for c in sul[:5]],
        "delta_custo_unit_sul_menos_regiao_brl": delta_custo,
        "delta_impostos_sul_menos_regiao_brl": delta_impostos,
        "veredito": veredito,
        "portos_preferidos": pref["portos_preferidos"],
        "portos_sul_comparados": pref["portos_sul_comparativo_tributacao"],
    }
