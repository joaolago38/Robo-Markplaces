"""
integracoes/filamentos/sourcing_filamentos.py
Decide sourcing de filamento 3D: COMPRAR_BR vs IMPORTAR_CHINA vs NAO_COMPENSA.

Usa catálogo nacional + custo landed China (custo_landed) + preços ML do monitor.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import (
    FILAMENTOS_SOURCING_CATALOGO_BR,
    FILAMENTOS_SOURCING_MARGEM_MIN_PCT,
    FILAMENTOS_SOURCING_MOQ_CHINA,
    FILAMENTOS_SOURCING_NCM,
    FILAMENTOS_SOURCING_TAXA_ML_PCT,
    ROOT,
)
from integracoes.filamentos.contexto_importacao_filamento import (
    anexar_contexto_filamento,
    params_landed_filamento,
)
from integracoes.importacao.custo_landed import calcular_cenarios_frete, calcular_margem_revenda

logger = logging.getLogger("sourcing_filamentos")

# FOB fallback (USD/kg) quando não há oferta Alibaba na rodada
_FOB_USD_FALLBACK: dict[str, float] = {
    "PLA": 4.5,
    "PETG": 5.0,
    "ABS": 5.0,
    "TPU": 7.0,
}

VEREDITOS = frozenset({"COMPRAR_BR", "IMPORTAR_CHINA", "NAO_COMPENSA"})


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _material_norm(mat: str | None) -> str:
    m = str(mat or "").strip().upper()
    if m.startswith("PLA"):
        return "PLA"
    return m


def custo_br_unitario(entrada: dict[str, Any]) -> float:
    """Prefer custo_unitario_brl; senão base × (1 + IPI%)."""
    direto = _f(entrada.get("custo_unitario_brl"))
    if direto > 0:
        return round(direto, 2)
    base = _f(entrada.get("preco_base_brl"))
    ipi = _f(entrada.get("ipi_pct"), 0.0)
    if base <= 0:
        return 0.0
    return round(base * (1.0 + ipi / 100.0), 2)


def carregar_fornecedores_br(caminho: str | None = None) -> list[dict[str, Any]]:
    path = ROOT / (caminho or FILAMENTOS_SOURCING_CATALOGO_BR)
    data = ler_json(path, default=[])
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("ativo"):
            continue
        custo = custo_br_unitario(item)
        if custo <= 0:
            continue
        out.append({**item, "custo_unitario_brl": custo, "material": _material_norm(item.get("material"))})
    return sorted(out, key=lambda x: int(x.get("prioridade") or 99))


def _precos_ml_por_material(
    consolidado: dict[str, Any] | None,
    resultados: list[dict[str, Any]] | None,
) -> dict[str, dict[str, float]]:
    """material -> {preco_min, preco_medio, preco_max}."""
    por: dict[str, dict[str, list[float]]] = {}
    for r in resultados or []:
        if not r.get("ok"):
            continue
        mat = _material_norm(str(r.get("material") or ""))
        if not mat or mat == "?":
            continue
        bucket = por.setdefault(mat, {"mins": [], "medios": [], "maxs": []})
        for chave, dest in (("preco_min", "mins"), ("preco_medio", "medios"), ("preco_max", "maxs")):
            v = _f(r.get(chave))
            if v > 0:
                bucket[dest].append(v)

    out: dict[str, dict[str, float]] = {}
    for mat, b in por.items():
        out[mat] = {
            "preco_min": round(min(b["mins"]), 2) if b["mins"] else 0.0,
            "preco_medio": round(sum(b["medios"]) / len(b["medios"]), 2) if b["medios"] else 0.0,
            "preco_max": round(max(b["maxs"]), 2) if b["maxs"] else 0.0,
        }

    # Fallback global do consolidado se material sem termo
    if consolidado and not out:
        medio = _f(consolidado.get("preco_medio"))
        if medio > 0:
            out["GERAL"] = {
                "preco_min": _f(consolidado.get("preco_min"), medio),
                "preco_medio": medio,
                "preco_max": _f(consolidado.get("preco_max"), medio),
            }
    return out


def _fob_do_cruzamento(cruzamento: dict[str, Any] | None, material: str) -> float | None:
    if not cruzamento or not cruzamento.get("ok"):
        return None
    melhor_global: float | None = None
    for c in cruzamento.get("cruzamentos") or []:
        if _material_norm(c.get("material")) != material:
            continue
        melhor = c.get("melhor_analise") or {}
        for chave in ("preco_usd", "fob_usd", "preco_fob_usd"):
            v = _f(melhor.get(chave))
            if v > 0:
                return v
        op = melhor.get("oportunidade") or {}
        v = _f(op.get("preco_usd"))
        if v > 0:
            return v
        # guarda qualquer FOB do material
        if melhor_global is None and v > 0:
            melhor_global = v
    return melhor_global


def _fob_do_catalogo_alibaba(material: str) -> float | None:
    from integracoes.filamentos.cruzamento_alibaba import carregar_produtos_filamento_alibaba

    for p in carregar_produtos_filamento_alibaba():
        if _material_norm(p.get("material")) != material:
            continue
        v = _f(p.get("preco_fob_usd"))
        if v > 0:
            return v
    return None


def resolver_fob_usd(
    material: str,
    *,
    cruzamento: dict[str, Any] | None = None,
    fob_usd_override: float | None = None,
) -> tuple[float, str]:
    if fob_usd_override is not None and fob_usd_override > 0:
        return float(fob_usd_override), "override"
    cruz = _fob_do_cruzamento(cruzamento, material)
    if cruz and cruz > 0:
        return cruz, "cruzamento_alibaba"
    cat = _fob_do_catalogo_alibaba(material)
    if cat and cat > 0:
        return cat, "catalogo_alibaba"
    fb = _FOB_USD_FALLBACK.get(material, 5.0)
    return fb, "fallback"


def _margens(preco_venda: float, custo: float, taxa_ml: float, margem_min: float) -> dict[str, Any]:
    ml = calcular_margem_revenda(
        preco_venda, custo, taxa_marketplace_pct=taxa_ml, margem_minima_pct=margem_min
    )
    direto = calcular_margem_revenda(
        preco_venda, custo, taxa_marketplace_pct=0.0, margem_minima_pct=margem_min
    )
    return {"ml": ml, "direto": direto}


def _lucro_liquido_ml(margens: dict[str, Any]) -> float:
    m = margens.get("ml") or {}
    if not m.get("ok"):
        return -9999.0
    return float(m.get("margem_brl") or 0)


def decidir_veredito(
    *,
    custo_br: float | None,
    custo_china: float | None,
    margens_br: dict[str, Any] | None,
    margens_china: dict[str, Any] | None,
    margem_min_pct: float,
) -> tuple[str, str]:
    """Retorna (veredito, motivo)."""
    luc_br = _lucro_liquido_ml(margens_br or {}) if custo_br and custo_br > 0 else None
    luc_cn = _lucro_liquido_ml(margens_china or {}) if custo_china and custo_china > 0 else None

    def _ok(margens: dict[str, Any] | None) -> bool:
        m = (margens or {}).get("ml") or {}
        return bool(m.get("lucro_razoavel"))

    candidatos: list[tuple[str, float]] = []
    if luc_br is not None and luc_br > 0 and _ok(margens_br):
        candidatos.append(("COMPRAR_BR", luc_br))
    if luc_cn is not None and luc_cn > 0 and _ok(margens_china):
        candidatos.append(("IMPORTAR_CHINA", luc_cn))

    if not candidatos:
        # sem margem mínima: ainda escolhe o menos pior se houver lucro positivo
        fallback: list[tuple[str, float]] = []
        if luc_br is not None and luc_br > 0:
            fallback.append(("COMPRAR_BR", luc_br))
        if luc_cn is not None and luc_cn > 0:
            fallback.append(("IMPORTAR_CHINA", luc_cn))
        if not fallback:
            return "NAO_COMPENSA", f"sem_margem_ml_min_{margem_min_pct}pct"
        fallback.sort(key=lambda x: x[1], reverse=True)
        return fallback[0][0], "lucro_positivo_abaixo_piso"

    candidatos.sort(key=lambda x: x[1], reverse=True)
    melhor = candidatos[0]
    if len(candidatos) > 1 and candidatos[0][1] == candidatos[1][1]:
        # empate: prefere BR (menos risco operacional)
        if any(c[0] == "COMPRAR_BR" for c in candidatos if c[1] == melhor[1]):
            return "COMPRAR_BR", "empate_prefere_br"
    return melhor[0], f"maior_lucro_ml={melhor[1]:.2f}"


def analisar_material(
    material: str,
    *,
    fornecedor_br: dict[str, Any] | None,
    precos_ml: dict[str, float],
    cambio_usd_brl: float,
    cruzamento: dict[str, Any] | None = None,
    fob_usd: float | None = None,
    moq_china: int | None = None,
    preco_venda_brl: float | None = None,
) -> dict[str, Any]:
    mat = _material_norm(material)
    venda = _f(preco_venda_brl)
    if venda <= 0:
        venda = _f(precos_ml.get("preco_medio")) or _f(precos_ml.get("preco_min"))
    taxa_ml = FILAMENTOS_SOURCING_TAXA_ML_PCT
    margem_min = FILAMENTOS_SOURCING_MARGEM_MIN_PCT
    qty = max(1, int(moq_china or FILAMENTOS_SOURCING_MOQ_CHINA))

    custo_br = custo_br_unitario(fornecedor_br) if fornecedor_br else 0.0
    margens_br = _margens(venda, custo_br, taxa_ml, margem_min) if custo_br > 0 and venda > 0 else None

    fob, fonte_fob = resolver_fob_usd(mat, cruzamento=cruzamento, fob_usd_override=fob_usd)
    landed = None
    custo_china = None
    margens_china = None
    params_imp = params_landed_filamento(fornecedor_br)
    if fob > 0 and cambio_usd_brl > 0:
        landed = calcular_cenarios_frete(
            fob,
            cambio_usd_brl=cambio_usd_brl,
            peso_kg_unit=_f((fornecedor_br or {}).get("peso_kg"), 1.0) or 1.0,
            quantidade=qty,
            ii_pct=params_imp["ii_pct"],
            ipi_pct=params_imp["ipi_pct"],
            pis_pct=params_imp["pis_pct"],
            cofins_pct=params_imp["cofins_pct"],
            icms_pct=params_imp["icms_pct"],
            siscomex_brl=params_imp["siscomex_brl"],
            siscomex_adicoes=params_imp["siscomex_adicoes"],
            desembaraco_brl=params_imp["desembaraco_brl"],
            afrmm_pct=params_imp["afrmm_pct"],
        )
        mar = landed.get("maritimo") or {}
        if mar.get("ok"):
            custo_china = _f(mar.get("custo_unitario_brl"))
            if custo_china > 0 and venda > 0:
                margens_china = _margens(venda, custo_china, taxa_ml, margem_min)

    veredito, motivo = decidir_veredito(
        custo_br=custo_br or None,
        custo_china=custo_china,
        margens_br=margens_br,
        margens_china=margens_china,
        margem_min_pct=margem_min,
    )

    mar_landed = (landed or {}).get("maritimo") or {}
    aer_landed = (landed or {}).get("aereo") or {}

    return {
        "ok": True,
        "material": mat,
        "ncm": params_imp.get("ncm") or FILAMENTOS_SOURCING_NCM,
        "cnpj_importador": params_imp.get("cnpj_importador"),
        "cep_destino": params_imp.get("cep_destino"),
        "preco_venda_brl": round(venda, 2) if venda > 0 else None,
        "precos_ml": precos_ml,
        "fornecedor_br": {
            "id": (fornecedor_br or {}).get("id"),
            "fornecedor": (fornecedor_br or {}).get("fornecedor"),
            "custo_unitario_brl": custo_br or None,
        }
        if fornecedor_br
        else None,
        "china": {
            "fob_usd": round(fob, 4),
            "fonte_fob": fonte_fob,
            "moq": qty,
            "cambio_usd_brl": round(cambio_usd_brl, 4),
            "custo_unitario_maritimo_brl": custo_china,
            "custo_unitario_aereo_brl": _f(aer_landed.get("custo_unitario_brl")) or None,
            "melhor_frete": (landed or {}).get("melhor_frete"),
            "siscomex_brl": params_imp.get("siscomex_brl"),
            "siscomex_adicoes": params_imp.get("siscomex_adicoes"),
            "afrmm_brl": mar_landed.get("afrmm_brl"),
            "despesas_aduaneiras_inclusas": True,
            "impostos_maritimo": {
                "ii_brl": mar_landed.get("ii_brl"),
                "ipi_brl": mar_landed.get("ipi_brl"),
                "pis_cofins_brl": mar_landed.get("pis_cofins_brl"),
                "icms_brl": mar_landed.get("icms_brl"),
                "siscomex_brl": mar_landed.get("siscomex_brl"),
                "afrmm_brl": mar_landed.get("afrmm_brl"),
                "impostos_total_brl": mar_landed.get("impostos_total_brl"),
            }
            if mar_landed.get("ok")
            else None,
        },
        "margens_br": margens_br,
        "margens_china_maritimo": margens_china,
        "veredito": veredito,
        "motivo": motivo,
    }


def analisar_sourcing(
    consolidado: dict[str, Any] | None = None,
    resultados: list[dict[str, Any]] | None = None,
    *,
    cruzamento: dict[str, Any] | None = None,
    cambio_usd_brl: float | None = None,
    fornecedores_br: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Compara compra BR vs importação China por material com preço ML.
    """
    if cambio_usd_brl is None:
        try:
            from integracoes.cambio.cotacao_usd import obter_cotacao_usd

            cot = obter_cotacao_usd()
            cambio_usd_brl = _f(cot.get("usd_brl"), 5.55)
        except Exception as exc:
            logger.warning("Câmbio indisponível para sourcing filamentos: %s", exc)
            cambio_usd_brl = 5.55

    forn = fornecedores_br if fornecedores_br is not None else carregar_fornecedores_br()
    precos_por_mat = _precos_ml_por_material(consolidado, resultados)

    # Materiais a analisar: união de BR ativos + ML + fallbacks
    materiais: set[str] = set()
    for f in forn:
        materiais.add(_material_norm(f.get("material")))
    materiais.update(precos_por_mat.keys())
    materiais.discard("GERAL")
    materiais.discard("")

    por_forn = {_material_norm(f.get("material")): f for f in forn}
    analises: list[dict[str, Any]] = []
    for mat in sorted(materiais):
        precos = precos_por_mat.get(mat) or precos_por_mat.get("GERAL") or {}
        if not precos and mat not in por_forn:
            continue
        analises.append(
            analisar_material(
                mat,
                fornecedor_br=por_forn.get(mat),
                precos_ml=precos,
                cambio_usd_brl=float(cambio_usd_brl),
                cruzamento=cruzamento,
            )
        )

    resumo = {
        "COMPRAR_BR": sum(1 for a in analises if a.get("veredito") == "COMPRAR_BR"),
        "IMPORTAR_CHINA": sum(1 for a in analises if a.get("veredito") == "IMPORTAR_CHINA"),
        "NAO_COMPENSA": sum(1 for a in analises if a.get("veredito") == "NAO_COMPENSA"),
    }

    # Cálculo de referência (melhor marítimo entre análises) para breakdown Siscomex/aduaneiro
    calc_ref = None
    for a in analises:
        imp = (a.get("china") or {}).get("impostos_maritimo")
        if imp and imp.get("impostos_total_brl"):
            calc_ref = {
                "ok": True,
                "ii_brl": imp.get("ii_brl"),
                "ipi_brl": imp.get("ipi_brl"),
                "pis_cofins_brl": imp.get("pis_cofins_brl"),
                "icms_brl": imp.get("icms_brl"),
                "siscomex_brl": (a.get("china") or {}).get("siscomex_brl"),
                "afrmm_brl": imp.get("afrmm_brl"),
                "custo_total_brl": (a.get("china") or {}).get("custo_unitario_maritimo_brl"),
                "custo_unitario_brl": (a.get("china") or {}).get("custo_unitario_maritimo_brl"),
                "impostos_total_brl": imp.get("impostos_total_brl"),
            }
            break

    payload = {
        "ok": True,
        "cambio_usd_brl": round(float(cambio_usd_brl), 4),
        "ncm": FILAMENTOS_SOURCING_NCM,
        "moq_china_padrao": FILAMENTOS_SOURCING_MOQ_CHINA,
        "fornecedores_br": len(forn),
        "analises": analises,
        "resumo_vereditos": resumo,
    }
    return anexar_contexto_filamento(payload, calculo=calc_ref)


def formatar_secao_sourcing(sourcing: dict[str, Any] | None, *, fmt_brl) -> list[str]:
    if not sourcing or not sourcing.get("ok"):
        return []
    linhas = [
        "",
        "*Sourcing BR × China*",
        f"_NCM {sourcing.get('ncm')} · MOQ China {sourcing.get('moq_china_padrao')} kg · "
        f"câmbio R$ {sourcing.get('cambio_usd_brl')}_",
    ]
    ctx = sourcing.get("contexto_importacao_cnpj") or {}
    cnpj = (ctx.get("cnpj") or {}).get("cnpj_formatado") or (ctx.get("cnpj") or {}).get("cnpj")
    cep = (ctx.get("cep") or {}).get("destino_cep")
    if cnpj or cep:
        linhas.append(
            f"_Importação CNPJ `{cnpj or '?'}` · CEP `{cep or '13467-694'}` · "
            f"Siscomex vigente (DI+adições)_"
        )
    bloco = sourcing.get("bloco_telegram_importacao_cnpj")
    # bloco completo no fim da seção (após vereditos)
    analises = sourcing.get("analises") or []
    if not analises:
        linhas.append("_Sem materiais com custo BR ou preço ML para decidir._")
        return linhas

    for a in analises:
        mat = a.get("material") or "?"
        ver = a.get("veredito") or "?"
        emoji = {"COMPRAR_BR": "✅", "IMPORTAR_CHINA": "🚢", "NAO_COMPENSA": "⛔"}.get(ver, "•")
        br = (a.get("fornecedor_br") or {}).get("custo_unitario_brl")
        cn = (a.get("china") or {}).get("custo_unitario_maritimo_brl")
        venda = a.get("preco_venda_brl")
        luc_br = ((a.get("margens_br") or {}).get("ml") or {}).get("margem_brl")
        luc_cn = ((a.get("margens_china_maritimo") or {}).get("ml") or {}).get("margem_brl")
        linhas.append(
            f"{emoji} *{mat}* → `{ver}`\n"
            f"  Venda ML {fmt_brl(venda)} | BR {fmt_brl(br)} | China mar. {fmt_brl(cn)}\n"
            f"  Lucro ML: BR {fmt_brl(luc_br)} · China {fmt_brl(luc_cn)}"
        )

    resumo = sourcing.get("resumo_vereditos") or {}
    linhas.append(
        f"_Resumo: BR {resumo.get('COMPRAR_BR', 0)} · "
        f"China {resumo.get('IMPORTAR_CHINA', 0)} · "
        f"não compensa {resumo.get('NAO_COMPENSA', 0)}_"
    )
    if bloco:
        linhas.extend(["", bloco])
    return linhas
