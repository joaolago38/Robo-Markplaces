"""
integracoes/importacao/tributacao_py_br.py
Cruzamento tributário Paraguai × Brasil para mercadorias oriundas do PY.

Cenários (estimativa de planejamento — confirme com despachante/contador):
  A) Importação direta China→BR (II cheio + PIS/COFINS + ICMS + AFRMM)
  B) Origem PY + Certificado/Declaração Mercosul → II = 0% no BR;
     permanecem PIS/COFINS-Importação, IPI (se houver), ICMS, Siscomex
  C) Passagem pelo PY sem origem qualificável → II cheio (pior)

Lado PY (referência):
  - IVA geral ~10% (exportação de mercadorias tipicamente desonerada)
  - Maquila: imposto único ~1% sobre valor agregado (opcional)
  - Custo estim. de certificado/declaração de origem

Refs: ACE-18 / Regime de Origem Mercosul (CMC 05/23) · Lei 10.865/2004 ·
      IVA Paraguai · Lei de Maquila (quando aplicável).
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from core.horario import agora_brasil
from integracoes.importacao.custo_landed import calcular_margem_revenda
from integracoes.importacao.siscomex import taxa_siscomex_brl

logger = logging.getLogger("tributacao_py_br")

SNAPSHOT_PATH = ROOT / "logs" / "tributacao_py_br_ultima.json"

# Defaults calibráveis via env / caller
IVA_PY_PCT = 10.0
MAQUILA_PCT = 1.0
CERTIFICADO_ORIGEM_BRL = 180.0  # estimativa emissão/despacho documental


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 1) -> int:
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return default


def _cfg():
    from core import config as cfg

    return cfg


def tributos_lado_paraguai(
    valor_mercadoria_brl: float,
    *,
    exportacao_para_br: bool = True,
    regime_maquila: bool = False,
    valor_agregado_py_brl: float | None = None,
    iva_pct: float | None = None,
    maquila_pct: float | None = None,
) -> dict[str, Any]:
    """
    Tributos/estimativas no lado PY.
    Exportação: IVA tipicamente 0; maquila opcional ~1% sobre VA.
    """
    base = max(0.0, _f(valor_mercadoria_brl))
    iva_aliq = _f(iva_pct, float(getattr(_cfg(), "HUB_PY_IVA_PCT", IVA_PY_PCT)))
    maq_aliq = _f(maquila_pct, float(getattr(_cfg(), "HUB_PY_MAQUILA_PCT", MAQUILA_PCT)))

    if exportacao_para_br:
        iva_brl = 0.0
        iva_nota = "Exportação PY→BR — IVA tipicamente desonerado (crédito/recuperação conforme regime)"
    else:
        iva_brl = round(base * (iva_aliq / 100.0), 2)
        iva_nota = f"IVA PY {iva_aliq}% sobre mercadoria (venda interna)"

    va = _f(valor_agregado_py_brl, base * 0.40)  # hipótese 40% conteúdo regional
    maquila_brl = round(va * (maq_aliq / 100.0), 2) if regime_maquila else 0.0

    total = iva_brl + maquila_brl
    return {
        "ok": True,
        "pais": "PY",
        "exportacao_para_br": exportacao_para_br,
        "regime_maquila": regime_maquila,
        "iva_pct": iva_aliq if not exportacao_para_br else 0.0,
        "iva_brl": iva_brl,
        "iva_nota": iva_nota,
        "maquila_pct": maq_aliq if regime_maquila else 0.0,
        "valor_agregado_estimado_brl": round(va, 2),
        "maquila_brl": maquila_brl,
        "total_tributos_py_brl": round(total, 2),
        "referencia": "IVA PY ~10% · Maquila ~1% VA (Lei Maquila) — estimativa",
    }


def tributos_entrada_brasil_desde_py(
    valor_aduaneiro_cif_brl: float,
    *,
    com_certificado_origem_mercosul: bool = True,
    ii_pct_sem_origem: float = 16.0,
    ipi_pct: float = 0.0,
    pis_pct: float | None = None,
    cofins_pct: float | None = None,
    icms_pct: float = 18.0,
    siscomex_brl: float | None = None,
    despesas_locais_brl: float = 0.0,
    afrmm_brl: float = 0.0,
) -> dict[str, Any]:
    """
    Cascata BR na entrada formal desde o Paraguai.
    Com origem Mercosul: II = 0%. Sem origem: II cheio (como terceiros).
    PIS/COFINS + ICMS + Siscomex permanecem na estimativa padrão.
    """
    cfg = _cfg()
    cif = max(0.0, _f(valor_aduaneiro_cif_brl))
    pis = _f(pis_pct, float(getattr(cfg, "IMPORTACAO_PIS_PCT", 2.1)))
    cofins = _f(cofins_pct, float(getattr(cfg, "IMPORTACAO_COFINS_PCT", 9.65)))
    sis = _f(siscomex_brl, taxa_siscomex_brl(adicoes=1))
    locais = max(0.0, _f(despesas_locais_brl)) + max(0.0, _f(afrmm_brl))

    ii_pct = 0.0 if com_certificado_origem_mercosul else _f(ii_pct_sem_origem, 16.0)
    ii_brl = cif * (ii_pct / 100.0)
    ipi_brl = (cif + ii_brl) * (_f(ipi_pct) / 100.0)
    pis_brl = cif * (pis / 100.0)
    cofins_brl = cif * (cofins / 100.0)

    base_sem_icms = cif + ii_brl + ipi_brl + pis_brl + cofins_brl + sis + locais
    aliq = _f(icms_pct, 18.0) / 100.0
    icms_brl = (base_sem_icms / (1.0 - aliq) * aliq) if 0 < aliq < 1 else 0.0
    total_imp = ii_brl + ipi_brl + pis_brl + cofins_brl + icms_brl
    custo_trib = base_sem_icms + icms_brl

    return {
        "ok": True,
        "pais": "BR",
        "acordo": "ACE-18 / Mercosul" if com_certificado_origem_mercosul else "sem_preferencia",
        "com_certificado_origem_mercosul": com_certificado_origem_mercosul,
        "valor_aduaneiro_cif_brl": round(cif, 2),
        "ii_pct": ii_pct,
        "ii_brl": round(ii_brl, 2),
        "ipi_pct": _f(ipi_pct),
        "ipi_brl": round(ipi_brl, 2),
        "pis_pct": pis,
        "pis_brl": round(pis_brl, 2),
        "cofins_pct": cofins,
        "cofins_brl": round(cofins_brl, 2),
        "pis_cofins_brl": round(pis_brl + cofins_brl, 2),
        "siscomex_brl": round(sis, 2),
        "despesas_locais_brl": round(locais, 2),
        "icms_pct": _f(icms_pct, 18.0),
        "icms_brl": round(icms_brl, 2),
        "impostos_total_brl": round(total_imp, 2),
        "custo_apos_tributos_brl": round(custo_trib, 2),
        "economia_ii_vs_cheia_brl": round(cif * (_f(ii_pct_sem_origem, 16.0) / 100.0), 2)
        if com_certificado_origem_mercosul
        else 0.0,
        "aviso": (
            "II zerado exige origem qualificável + certificado/declaração Mercosul. "
            "PIS/COFINS e ICMS normalmente permanecem. Confirme NCM e ROM com despachante."
        ),
    }


def cruzar_tributacao_py_br_produto(
    *,
    preco_origem_py_brl: float | None = None,
    fob_usd: float | None = None,
    cambio_usd_brl: float = 5.5,
    quantidade: int = 1,
    peso_kg_unit: float = 1.0,
    frete_internacional_brl: float = 0.0,
    seguro_pct: float = 0.5,
    ii_pct_china: float = 16.0,
    ipi_pct: float = 0.0,
    icms_pct: float = 18.0,
    preco_venda_ml_brl: float | None = None,
    taxa_marketplace_pct: float = 16.0,
    lucro_alvo_pct: float = 20.0,
    custos_logistica_py_br_unit: float = 0.0,
    regime_maquila: bool = False,
    certificado_origem_brl: float | None = None,
) -> dict[str, Any]:
    """
    Cruza 3 caminhos e aponta o de melhor lucro no marketplace.
    preco_origem_py_brl = preço da mercadoria já no PY (BRL).
    Se só houver FOB USD (China via hub), usa FOB*câmbio como base PY.
    """
    qty = _i(quantidade)
    cambio = _f(cambio_usd_brl, 5.5)
    if preco_origem_py_brl is not None and _f(preco_origem_py_brl) > 0:
        merc_unit = _f(preco_origem_py_brl)
        fonte_preco = "preco_py_brl"
    else:
        merc_unit = _f(fob_usd) * cambio
        fonte_preco = "fob_usd_x_cambio"
    if merc_unit <= 0:
        return {"ok": False, "motivo": "preço origem inválido"}

    merc_total = merc_unit * qty
    frete = _f(frete_internacional_brl)
    seguro = (merc_total + frete) * (_f(seguro_pct, 0.5) / 100.0)
    cif_total = merc_total + frete + seguro
    cif_unit = cif_total / qty

    cert_brl = _f(
        certificado_origem_brl,
        float(getattr(_cfg(), "HUB_PY_CERTIFICADO_ORIGEM_BRL", CERTIFICADO_ORIGEM_BRL)),
    )
    cert_unit = cert_brl / qty
    log_unit = _f(custos_logistica_py_br_unit)

    # --- Lado PY ---
    trib_py = tributos_lado_paraguai(
        merc_total,
        exportacao_para_br=True,
        regime_maquila=regime_maquila,
    )
    trib_py_unit = _f(trib_py.get("total_tributos_py_brl")) / qty

    # --- BR com origem Mercosul (II=0) ---
    br_origem = tributos_entrada_brasil_desde_py(
        cif_total,
        com_certificado_origem_mercosul=True,
        ii_pct_sem_origem=ii_pct_china,
        ipi_pct=ipi_pct,
        icms_pct=icms_pct,
    )
    # custo_apos = CIF + tributos BR; + PY + certificado + logística local (hub/terrestre)
    custo_origem_unit = (
        _f(br_origem.get("custo_apos_tributos_brl")) / qty + trib_py_unit + cert_unit + log_unit
    )

    # --- BR sem origem (II cheio) ---
    br_sem = tributos_entrada_brasil_desde_py(
        cif_total,
        com_certificado_origem_mercosul=False,
        ii_pct_sem_origem=ii_pct_china,
        ipi_pct=ipi_pct,
        icms_pct=icms_pct,
    )
    custo_sem_unit = _f(br_sem.get("custo_apos_tributos_brl")) / qty + trib_py_unit + log_unit

    # --- China direto (baseline) ---
    from integracoes.importacao.custo_landed import calcular_custo_landed

    fob_u = merc_unit / cambio if cambio > 0 else _f(fob_usd)
    china = calcular_custo_landed(
        fob_u if fob_u > 0 else _f(fob_usd, 1.0),
        cambio_usd_brl=cambio,
        peso_kg_unit=peso_kg_unit,
        quantidade=qty,
        modo_frete="maritimo",
        ii_pct=ii_pct_china,
        ipi_pct=ipi_pct,
        icms_pct=icms_pct,
    )
    custo_china_unit = _f(china.get("custo_unitario_brl"))

    venda = _f(preco_venda_ml_brl)
    cenarios = []
    for nome, custo_u, extra in (
        (
            "py_origem_mercosul",
            custo_origem_unit,
            {
                "ii_brl_unit": _f(br_origem.get("ii_brl")) / qty,
                "economia_ii_brl_unit": _f(br_origem.get("economia_ii_vs_cheia_brl")) / qty,
                "tributos_br": br_origem,
                "tributos_py": trib_py,
                "certificado_origem_unit_brl": round(cert_unit, 2),
            },
        ),
        (
            "py_sem_origem",
            custo_sem_unit,
            {
                "ii_brl_unit": _f(br_sem.get("ii_brl")) / qty,
                "economia_ii_brl_unit": 0.0,
                "tributos_br": br_sem,
                "tributos_py": trib_py,
                "certificado_origem_unit_brl": 0.0,
            },
        ),
        (
            "china_direto_br",
            custo_china_unit,
            {
                "ii_brl_unit": _f(china.get("ii_brl")) / qty,
                "economia_ii_brl_unit": 0.0,
                "tributos_br": china,
                "tributos_py": None,
                "certificado_origem_unit_brl": 0.0,
            },
        ),
    ):
        margem = (
            calcular_margem_revenda(
                venda,
                custo_u,
                taxa_marketplace_pct=taxa_marketplace_pct,
                margem_minima_pct=lucro_alvo_pct,
            )
            if venda > 0 and custo_u > 0
            else {"ok": False}
        )
        cenarios.append(
            {
                "cenario": nome,
                "custo_unitario_brl": round(custo_u, 2),
                "margem_marketplace": margem,
                "atinge_lucro_alvo": bool(
                    margem.get("ok") and _f(margem.get("margem_pct")) >= lucro_alvo_pct
                ),
                **extra,
            }
        )

    cenarios.sort(key=lambda c: _f(c.get("custo_unitario_brl"), 1e9))
    melhor = cenarios[0] if cenarios else {}
    melhor_lucro = None
    for c in cenarios:
        if c.get("atinge_lucro_alvo"):
            melhor_lucro = c
            break
    if melhor_lucro is None:
        # maior margem_pct
        com_m = [c for c in cenarios if (c.get("margem_marketplace") or {}).get("ok")]
        if com_m:
            melhor_lucro = max(com_m, key=lambda x: _f((x.get("margem_marketplace") or {}).get("margem_pct")))

    economia_origem_vs_china = None
    if custo_china_unit > 0 and custo_origem_unit > 0:
        economia_origem_vs_china = round(custo_china_unit - custo_origem_unit, 2)

    out = {
        "ok": True,
        "gerado_em": agora_brasil().isoformat(),
        "fonte_preco": fonte_preco,
        "quantidade": qty,
        "preco_origem_unit_brl": round(merc_unit, 2),
        "cif_unit_brl": round(cif_unit, 2),
        "preco_venda_ml_brl": round(venda, 2) if venda > 0 else None,
        "lucro_alvo_pct": lucro_alvo_pct,
        "taxa_marketplace_pct": taxa_marketplace_pct,
        "cenarios": cenarios,
        "melhor_custo": melhor.get("cenario"),
        "melhor_lucro_marketplace": (melhor_lucro or {}).get("cenario"),
        "economia_origem_mercosul_vs_china_unit_brl": economia_origem_vs_china,
        "recomendacao": _recomendar(melhor, melhor_lucro, economia_origem_vs_china),
        "aviso_legal": (
            "Estimativa. II=0% exige origem qualificável Mercosul. "
            "Não substitui assessoria fiscal/aduaneira PY e BR."
        ),
    }
    return out


def _recomendar(
    melhor_custo: dict[str, Any],
    melhor_lucro: dict[str, Any] | None,
    economia_vs_china: float | None,
) -> dict[str, Any]:
    cenario = (melhor_lucro or melhor_custo or {}).get("cenario")
    msgs = []
    if cenario == "py_origem_mercosul":
        msgs.append(
            "Preferir mercadoria com origem PY + certificado/declaração Mercosul (II=0 no BR)."
        )
        if economia_vs_china and economia_vs_china > 0:
            msgs.append(f"Economia vs China direta ≈ R$ {economia_vs_china}/un.")
    elif cenario == "china_direto_br":
        msgs.append("China direta ainda mais barata nesta simulação — revisar preço PY/logística.")
    else:
        msgs.append("Sem origem Mercosul o II volta a cheio — priorize certificado de origem.")

    margem = ((melhor_lucro or melhor_custo or {}).get("margem_marketplace") or {})
    if margem.get("lucro_razoavel"):
        msgs.append(f"Margem marketplace {margem.get('margem_pct')}% atinge o alvo.")
    elif margem.get("ok"):
        msgs.append(
            f"Margem {margem.get('margem_pct')}% abaixo do alvo — subir preço ML ou diluir logística."
        )

    return {
        "cenario_sugerido": cenario,
        "mensagens": msgs,
        "margem_pct": margem.get("margem_pct"),
        "custo_unitario_brl": (melhor_lucro or melhor_custo or {}).get("custo_unitario_brl"),
    }


def avaliar_tributacao_produtos_marketplace(
    produtos: list[dict[str, Any]] | None = None,
    *,
    cambio_usd_brl: float | None = None,
    lucro_alvo_pct: float = 20.0,
    regime_maquila: bool = False,
) -> dict[str, Any]:
    """Varre produtos (hub/filamentos) e cruza tributação PY×BR × lucro ML."""
    from integracoes.importacao.hub_paraguai_marketplace import (
        carregar_produtos_marketplace_hub,
        custo_rota_hub_py,
    )

    if cambio_usd_brl is None:
        try:
            from integracoes.cambio.cotacao_usd import obter_cotacao_usd

            cambio_usd_brl = _f(obter_cotacao_usd().get("usd_brl"), 5.5)
        except Exception:
            cambio_usd_brl = 5.5

    itens = produtos if produtos is not None else carregar_produtos_marketplace_hub()
    analises = []
    for p in itens:
        if not isinstance(p, dict) or not p.get("ativo", True):
            continue
        fob = _f(p.get("fob_usd") or p.get("preco_fob_usd"))
        qty = _i(p.get("quantidade") or 200)
        # logística hub (sem impostos BR) para embutir no cruzamento
        hub = custo_rota_hub_py(
            fob_usd=fob,
            cambio_usd_brl=float(cambio_usd_brl),
            quantidade=qty,
            peso_kg_unit=_f(p.get("peso_kg"), 1.0),
            volume_m3_unit=_f(p.get("volume_m3")) if p.get("volume_m3") is not None else None,
            cep_destino=p.get("cep_destino") or "13467-694",
        )
        # Frete CN→PY entra no CIF; hub+terrestre entram como logística (sem double-count)
        frete_cn_py = _f(hub.get("frete_china_py_brl")) if hub.get("ok") else 0.0
        hub_tot = _f((hub.get("hub_custos") or {}).get("custo_hub_total_brl"))
        terr_tot = _f((hub.get("terrestre_py_br") or {}).get("custo_total_brl"))
        log_unit = (hub_tot + terr_tot) / qty if hub.get("ok") else 0.0

        cruz = cruzar_tributacao_py_br_produto(
            fob_usd=fob,
            cambio_usd_brl=float(cambio_usd_brl),
            quantidade=qty,
            peso_kg_unit=_f(p.get("peso_kg"), 1.0),
            frete_internacional_brl=frete_cn_py,
            ii_pct_china=_f(p.get("ii_pct"), 12.6),
            ipi_pct=_f(p.get("ipi_pct"), 0.0),
            icms_pct=_f(p.get("icms_pct"), 18.0),
            preco_venda_ml_brl=_f(p.get("preco_venda_ml_brl")),
            taxa_marketplace_pct=_f(p.get("taxa_marketplace_pct"), 16.0),
            lucro_alvo_pct=lucro_alvo_pct,
            custos_logistica_py_br_unit=log_unit,
            regime_maquila=regime_maquila,
        )
        analises.append(
            {
                "produto_id": p.get("id"),
                "nome": p.get("nome"),
                "material": p.get("material"),
                "quantidade": qty,
                "cruzamento": cruz,
                "recomendacao": (cruz.get("recomendacao") or {}).get("cenario_sugerido"),
                "origem_melhor_que_sem_certificado": _origem_bate_sem(cruz),
                "origem_melhor_que_china": (
                    (cruz.get("melhor_custo") == "py_origem_mercosul")
                    or (
                        _f(cruz.get("economia_origem_mercosul_vs_china_unit_brl")) > 0
                    )
                ),
                "atinge_lucro_alvo": any(
                    c.get("atinge_lucro_alvo") for c in (cruz.get("cenarios") or [])
                ),
            }
        )

    preferem_origem = sum(
        1 for a in analises if a.get("recomendacao") == "py_origem_mercosul"
    )
    origem_vs_sem = sum(1 for a in analises if a.get("origem_melhor_que_sem_certificado"))
    origem_vs_china = sum(1 for a in analises if a.get("origem_melhor_que_china"))
    com_lucro = sum(1 for a in analises if a.get("atinge_lucro_alvo"))

    out = {
        "ok": True,
        "gerado_em": agora_brasil().isoformat(),
        "cambio_usd_brl": round(float(cambio_usd_brl), 4),
        "lucro_alvo_pct": lucro_alvo_pct,
        "regime_maquila": regime_maquila,
        "total_produtos": len(analises),
        "recomendam_origem_mercosul": preferem_origem,
        "origem_melhor_que_sem_certificado": origem_vs_sem,
        "origem_melhor_que_china": origem_vs_china,
        "atingem_lucro_alvo": com_lucro,
        "analises": analises,
        "dica_lucro": (
            "Para mercadoria oriunda do PY: sempre buscar certificado/declaração Mercosul "
            "(II=0%). Sem origem o II volta cheio e come a margem. "
            "Compare o custo total com China direta — se hub+terrestre forem altos, "
            "suba lote ou preço ML até margem alvo."
        ),
        "aviso_legal": (
            "Cruzamento tributário PY×BR estimativo. II=0% só com origem Mercosul válida."
        ),
    }
    gauge("trib_py_br.produtos", float(len(analises)))
    gauge("trib_py_br.origem_mercosul", float(preferem_origem))
    gauge("trib_py_br.origem_vs_china", float(origem_vs_china))
    gauge("trib_py_br.lucro_ok", float(com_lucro))
    incrementar("trib_py_br.ok")
    try:
        escrever_json_atomico(SNAPSHOT_PATH, out)
    except OSError as exc:
        logger.debug("snapshot trib py br: %s", exc)
    return out


def _origem_bate_sem(cruz: dict[str, Any]) -> bool:
    by = {c.get("cenario"): c for c in (cruz.get("cenarios") or [])}
    o = by.get("py_origem_mercosul") or {}
    s = by.get("py_sem_origem") or {}
    if not o or not s:
        return False
    return _f(o.get("custo_unitario_brl"), 1e9) < _f(s.get("custo_unitario_brl"), 1e9)

def formatar_tributacao_py_br_telegram(resultado: dict[str, Any], *, max_itens: int = 6) -> str:
    if not resultado.get("ok"):
        return f"Tributação PY×BR: {resultado.get('motivo', 'falhou')}"

    linhas = [
        "*Tributação Paraguai × Brasil* (Mercosul)",
        f"Câmbio R$ {resultado.get('cambio_usd_brl')} · lucro alvo "
        f"*{resultado.get('lucro_alvo_pct')}%*",
        f"Produtos: {resultado.get('total_produtos')} · "
        f"origem > sem cert.: *{resultado.get('origem_melhor_que_sem_certificado')}* · "
        f"origem > China: *{resultado.get('origem_melhor_que_china')}* · "
        f"atingem lucro: *{resultado.get('atingem_lucro_alvo')}*",
        "",
    ]
    for a in (resultado.get("analises") or [])[:max_itens]:
        cruz = a.get("cruzamento") or {}
        rec = cruz.get("recomendacao") or {}
        linhas.append(
            f"• *{a.get('nome') or a.get('produto_id')}* → `{a.get('recomendacao')}`\n"
            f"  Economia vs China: R$ {cruz.get('economia_origem_mercosul_vs_china_unit_brl')}/un · "
            f"custo sugerido R$ {rec.get('custo_unitario_brl')} · "
            f"margem {rec.get('margem_pct')}%"
        )
        for c in (cruz.get("cenarios") or [])[:3]:
            m = c.get("margem_marketplace") or {}
            flag = "OK" if c.get("atinge_lucro_alvo") else "—"
            linhas.append(
                f"    · {c.get('cenario')}: custo R$ {c.get('custo_unitario_brl')} · "
                f"margem {m.get('margem_pct')}% [{flag}]"
            )
    linhas.append(f"_{resultado.get('aviso_legal')}_")
    return "\n".join(linhas)
